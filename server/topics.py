import datetime as dt
import hashlib
import json
import re

from .creative import recommendations
from .store import dump, now


def check_topic(c, tenant, topic):
    if not topic or not topic.get("eventId"):
        return
    profile = json.loads(
        c.execute("SELECT profile FROM merchant WHERE id=?", (tenant,)).fetchone()[0]
    )
    row = c.execute(
        """SELECT e.* FROM event e LEFT JOIN event_feed f ON f.id=e.feed_id
                       WHERE e.id=? AND (e.city=? OR (e.is_news AND e.city='全部地区')) AND e.ends>=date(?,CASE WHEN e.is_news THEN '-6 days' ELSE '+0 days' END) AND
                       (e.feed_id IS NULL OR (f.enabled=1 AND datetime(f.checked)>=datetime('now','-48 hours')))""",
        (topic["eventId"], profile.get("city", ""), dt.date.today().isoformat()),
    ).fetchone()
    if not row or any(
        row[k] != topic[k] for k in ("title", "starts", "ends", "source") if k in topic
    ):
        raise ValueError("这项营销事件已更新或失效，请重新查看本周推荐。")


def weekly(c, tenant, profile, history):
    today = dt.date.today()
    wk = today.isocalendar()
    week = f"{wk.year}-W{wk.week:02d}"
    candidates = c.execute(
        """SELECT e.*, f.name AS publisher FROM event e LEFT JOIN event_feed f ON f.id=e.feed_id
           WHERE (e.city=? OR (e.is_news AND e.city='全部地区')) AND e.ends>=date(?,CASE WHEN e.is_news THEN '-6 days' ELSE '+0 days' END) AND e.starts<=? AND
           (e.feed_id IS NULL OR (f.enabled=1 AND datetime(f.checked)>=datetime('now','-48 hours')))
           ORDER BY e.starts,e.id""",
        (
            profile.get("city", ""),
            today.isoformat(),
            (today + dt.timedelta(days=7)).isoformat(),
        ),
    )
    context = " ".join(
        profile.get(k, "") for k in ("product", "industry", "audience", "facts")
    )

    def relevant(e):
        terms = re.split(r"[、，,\s]+", e["keywords"].strip())
        return not e["keywords"] or any(term and term in context for term in terms)

    events = [e for e in candidates if relevant(e)]
    events.sort(
        key=lambda e: (
            sum(e["title"] in h.get("original", "") for h in history),
            not bool(e["keywords"]),
            (-1 if e["is_news"] else 1)
            * dt.date.fromisoformat(e["starts"]).toordinal(),
        )
    )
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
            "eventId": e["id"],
            "starts": e["starts"],
            "ends": e["ends"],
            "basis": (
                f"日期和地区来自{e['publisher']}。"
                if e["feed_id"]
                else "运营已核实活动日期与地点。"
            ),
            "relevance": f"围绕{subject}，适用行业或关键词为{e['keywords']}。"
            if e["is_news"]
            else f"经营地区为{e['city']}，围绕{subject}选题。",
            "recentUses": sum(e["title"] in h.get("original", "") for h in history),
            "source": e["source"],
        }
        if e["is_news"]:
            item["brief"] = (
                f"{e['publisher']}于 {e['starts']} 发布了「{e['title']}」。"
                f"结合{subject}为感兴趣的顾客做一次主题分享，保留消息来源，避免暗示合作。"
            )
            item["basis"] = f"公告标题与发布日期来自{e['publisher']}。"
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
        identity = {
            k: v
            for k, v in item.items()
            if k not in ("recentUses", "relevance", "eventId", "starts", "ends")
        }
        key = hashlib.sha256(dump(identity).encode()).hexdigest()[:24]
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
