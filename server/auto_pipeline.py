"""Shared copy checkpoint for the independently routed one-click pipeline."""
import copy
import json
import threading
from . import model
from .campaign import LOCKED
from .creative import generate_copy
from .store import db, dump

COPY_LOCK = threading.Lock()


def shared_copy(spec):
    plan = spec['plan']
    result = copy.deepcopy(spec['replacement'])
    run_id = plan.get('creationRun')
    if not run_id or not model.route('text')['model']:
        return result
    # The group uses one approved draft even when image/video jobs start together.
    with COPY_LOCK:
        with db() as c:
            row = c.execute('SELECT plan FROM creative_run WHERE id=?', (run_id,)).fetchone()
        summary = json.loads(row[0])
        if summary.get('copyError'):
            raise ValueError(summary['copyError'])
        approved = summary.get('sharedCopy')
        if not approved:
            writing = copy.deepcopy(plan)
            writing['kind'] = 'copy'
            try:
                approved = generate_copy(writing)
                if approved.get('reviewFlag'):
                    raise ValueError('文案模型未通过资料复核，请检查文案连接或补充需求后重试。')
                if locked := LOCKED.search(plan['original']):
                    approved['title'] = locked.group(1)
                # Exact commercial details remain shared, including all caveats.
                facts = plan['coordination']['facts']
                missing = [fact for fact in facts if fact not in approved['body']]
                if missing:
                    approved['body'] += '；' + '；'.join(missing)
                summary['sharedCopy'] = approved
            except Exception as exc:
                summary['copyError'] = '文案制作未完成，请检查文案模型配置后重试此项。'
                with db(True) as c:
                    c.execute('UPDATE creative_run SET plan=? WHERE id=?', (dump(summary),run_id))
                raise ValueError(summary['copyError']) from exc
            with db(True) as c:
                c.execute('UPDATE creative_run SET plan=?,title=? WHERE id=?', (dump(summary),approved['title'],run_id))
    result.update({k:approved[k] for k in ('title','body','cta','engine','review') if k in approved})
    role = plan.get('bundleRole')
    if role in ('scene','white','livebackground','box','bag','card'):
        result['title'] = ''
    elif role == 'price':
        result['title'] = result.get('offer') or approved['title']
    elif role == 'closing':
        result['title'] = approved['cta'] or approved['title']
    result['detailLine'] = result['body']
    return result
