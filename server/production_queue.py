"""Dispatch durable jobs in round-robin tenant order on the existing local worker pool."""

from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock

from .store import db


class ProductionQueue:
    def __init__(self, workers):
        self.workers = workers
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trupic")
        self.lock = Lock()
        self.pending = OrderedDict()
        self.active = 0

    def submit(self, produce, job):
        with db() as c:
            row = c.execute("SELECT tenant FROM job WHERE id=?", (job,)).fetchone()
        future = Future()
        if row is None:
            future.set_exception(ValueError("找不到待制作任务。"))
            return future
        with self.lock:
            self.pending.setdefault(row["tenant"], deque()).append(
                (produce, job, future)
            )
            if self.active < self.workers:
                self.active += 1
                self.pool.submit(self._drain)
        return future

    def _drain(self):
        while True:
            with self.lock:
                if not self.pending:
                    self.active -= 1
                    return
                tenant, group = self.pending.popitem(last=False)
                produce, job, future = group.popleft()
                if group:
                    self.pending[tenant] = group
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(produce(job))
                except Exception as exc:
                    future.set_exception(exc)
