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
        dump([profile, [dict(e) for e in events], history[:3]]).encode()
    ).hexdigest()
    old = c.execute(
        "SELECT * FROM topics WHERE tenant=? AND week=?", (tenant, week)
    ).fetchone()
    if old and old["signature"] == signature:
        return json.loads(old["items"])
    items = recommendations(profile, history)
    if events:
        e = events[0]
        subject = profile.get("product") or profile.get("name") or "门店"
        item = {
            "id": week + "-" + e["id"],
            "title": e["title"],
            "tag": "本地活动",
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
    return items
