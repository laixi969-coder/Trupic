"""Shared copy checkpoint for the independently routed one-click pipeline."""
import copy
import json
import threading
from . import model
from .campaign import LOCKED
from .creative import draft_copy, generate_copy
from .store import db, dump

COPY_LOCK = threading.Lock()


def shared_copy(spec):
    plan = spec['plan']
    result = copy.deepcopy(spec['replacement'])
    run_id = plan.get('creationRun')
    if spec.get('copySelected') or not run_id or not model.route('text')['model']:
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
            failure_message = "文案制作未完成，请检查文案模型配置后重试此项。"
            try:
                approved = generate_copy(writing)
                flag = approved.get("reviewFlag")
                if flag == "模型调用未完成":
                    failure_message = approved.get("callError") or failure_message
                    raise ValueError(failure_message)
                if flag:
                    # Rebuild from verified merchant inputs; never release the rejected draft.
                    approved = draft_copy(writing)
                    approved.update(reviewFlag=flag, review=f"{flag}，使用已确认资料重新成稿。",
                                    attemptedModel=model.route("text")["model"])
                if locked := LOCKED.search(plan['original']):
                    approved['title'] = locked.group(1)
                # Exact commercial details remain shared, including all caveats.
                facts = plan['coordination']['facts']
                missing = [fact for fact in facts if fact not in approved['body']]
                if missing:
                    approved['body'] += '；' + '；'.join(missing)
                summary['sharedCopy'] = approved
            except Exception as exc:
                summary['copyError'] = failure_message
                with db(True) as c:
                    c.execute('UPDATE creative_run SET plan=? WHERE id=?', (dump(summary),run_id))
                raise ValueError(summary['copyError']) from exc
            with db(True) as c:
                c.execute('UPDATE creative_run SET plan=?,title=? WHERE id=?', (dump(summary),approved['title'],run_id))
    result.update({k:approved[k] for k in ('title','body','cta','engine','review','writingSkill','reviewFlag','attemptedModel','detailLine') if k in approved})
    role = plan.get('bundleRole')
    if role in ('scene','white','livebackground','box','bag','card'):
        result['title'] = ''
    elif role == 'price':
        result['title'] = result.get('offer') or approved['title']
    elif role == 'closing':
        result['title'] = approved['cta'] or approved['title']
    result['detailLine'] = result.get('detailLine') or result['body']
    return result
