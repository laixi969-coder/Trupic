import datetime as dt
import hashlib
import json

from .creative import recommendations
from .store import dump, now


def weekly(c, tenant, profile, history):
    today = dt.date.today()
    wk = today.isocalendar()
    week = f"{wk.year}-W{wk.week:02d}"
    events = c.execute(
        "SELECT * FROM event WHERE city=? AND ends>=? AND starts<=? ORDER BY starts LIMIT 2",
        (
            profile.get("city", ""),
            today.isoformat(),
            (today + dt.timedelta(days=7)).isoformat(),
        ),
    ).fetchall()
    signature = hashlib.sha256(
        dump([profile, [dict(e) for e in events], history]).encode()
    ).hexdigest()
    old = c.execute(
        "SELECT * FROM topics WHERE tenant=? AND week=?", (tenant, week)
    ).fetchone()
    if old and old["signature"] == signature:
        return topic_status(c, tenant, json.loads(old["items"]))
    items = recommendations(profile, history)
    if events:
        e = events[0]
        subject = profile.get("product") or profile.get("name") or "门店"
        item = {
            "id": week + "-" + e["id"],
            "title": e["title"],
            "tag": e["category"],
            "brief": f"{e['city']}的「{e['title']}」将在 {e['starts']} 至 {e['ends']} 举行。结合{subject}写一份面向附近顾客的邀请，请勿暗示门店与活动有合作。",
            "icon": "calendar",
            "week": week,
            "basis": "运营已核实活动日期与地点。",
            "source": e["source"],
        }
        items = [item] + items[:2]
    c.execute(
        "INSERT INTO topics VALUES(?,?,?,?,?) ON CONFLICT(tenant,week) DO UPDATE SET signature=excluded.signature,items=excluded.items,updated=excluded.updated",
        (tenant, week, signature, dump(items), now()),
    )
    return topic_status(c, tenant, items)


def topic_status(c, tenant, items):
    result = []
    for item in items:
        # A merchant can change their product during the same calendar week.
        key = hashlib.sha256(dump(item).encode()).hexdigest()[:24]
        row = c.execute(
            "SELECT first_work FROM topic_record WHERE tenant=? AND id=?", (tenant, key)
        ).fetchone()
        if row is None:
            # Attribute older completed works only when their exact saved topic matches.
            legacy = c.execute(
                """SELECT w.id FROM work w JOIN version v ON v.work=w.id AND v.n=1
                   WHERE w.tenant=? AND json_extract(v.spec,'$.source')=?
                   AND json_extract(v.spec,'$.plan.original')=? ORDER BY w.created LIMIT 1""",
                (tenant, item["id"], item["brief"]),
            ).fetchone()
            work = legacy[0] if legacy else None
            c.execute(
                "INSERT OR IGNORE INTO topic_record VALUES(?,?,?,?)",
                (tenant, key, dump(item), work),
            )
        else:
            work = row["first_work"]
        result.append({**item, "topicId": key, "adopted": bool(work)})
    return sorted(result, key=lambda item: item["adopted"])
