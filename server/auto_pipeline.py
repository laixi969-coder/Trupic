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
    if spec.get('copySelected') or not run_id:
        return result
    # The group uses one approved draft even when image/video jobs start together.
    with COPY_LOCK:
        with db() as c:
            row = c.execute('SELECT plan FROM creative_run WHERE id=?', (run_id,)).fetchone()
        summary = json.loads(row[0])
        if summary.get('copyError'):
            raise ValueError(summary['copyError'])
        approved = summary.get('sharedCopy')
        if not approved or approved.get("engine") == "本地创意规则":
            if not model.engine_name():
                raise ValueError("请在模型平台启用文字模型后重试文案。")
            writing = copy.deepcopy(plan)
            roles = plan.get("coordination", {}).get("roles", [])
            if roles == ["copy", "motion"]:
                writing["kind"] = "video"
            elif roles == ["copy"]:
                writing["kind"] = "copy"
            else:
                writing["kind"] = "poster"
            failure_message = "文案制作未完成，请检查文案模型配置后重试此项。"
            try:
                approved = generate_copy(writing)
                flag = approved.get("reviewFlag")
                if flag and flag != "模型调用未完成":
                    approved = generate_copy(writing, revision_note=approved.get("revisionNote") or flag)
                    flag = approved.get("reviewFlag")
                if flag:
                    failure_message = approved.get("callError") or f"文案未通过检查（{flag}）：{approved.get('revisionNote') or '请重试文案。'}"
                    raise ValueError(failure_message)
                if locked := LOCKED.search(plan['original']):
                    approved['title'] = locked.group(1)
                # Exact commercial details remain shared, including all caveats.
                facts = plan['coordination']['facts']
                missing = [fact for fact in facts if fact.strip() != plan['original'].strip() and fact not in approved['body']]
                if missing and writing["kind"] != "poster":
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
    if spec["kind"] == "copy" and approved.get("writingSkill", {}).get("posterHeadings"):
        from .campaign import complete_body
        result["body"] = complete_body(plan, result["body"], result["offer"], result["terms"])
    role = plan.get('bundleRole')
    if role in ('scene','white','livebackground','box','bag','card'):
        result['title'] = ''
    elif role == 'price':
        result['title'] = result.get('offer') or approved['title']
    elif role == 'closing':
        result['title'] = approved['cta'] or approved['title']
    result['detailLine'] = result.get('detailLine') or result['body']
    return result
