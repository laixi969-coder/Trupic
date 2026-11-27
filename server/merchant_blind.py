"""Blind merchant feedback on immutable deliveries, with settlement evidence on reveal."""

import json
import math
import secrets
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from flask import abort, jsonify, send_file

from .store import DATA, db, dump, ident, now

CATALOG = Path(__file__).parent / "data" / "merchant_blind_briefs.json"
MEDIA = {
    "video": ("video.mp4", "video/mp4"),
    "poster": ("poster.png", "image/png"),
    "copy": ("copy.txt", "text/plain; charset=utf-8"),
}
BRIEF_FIELDS = ("id", "sector", "sectorLabel", "title", "goal", "reviewerPrompt")


@lru_cache(maxsize=1)
def briefs():
    return {b["id"]: b for b in json.loads(CATALOG.read_text(encoding="utf-8"))}


def creation_draft(brief):
    facts = brief["facts"]
    offer = facts["offer"]
    if terms := facts.get("versionTerms"):
        current = terms[-1]
        offer = f"{current['weekday']}{current['channel']}价{current['amount']}元"
    medium = {"poster": "海报", "copy": "文案", "video": "视频"}[brief["kind"]]
    return "\n".join(
        (
            f"创作形式：{medium}",
            brief["brief"],
            f"商品或服务：{facts['product']}。{offer}。",
            "适用条件：" + "；".join(facts["conditions"]) + "。",
            "创作限制：" + "；".join(brief["avoid"]) + "。",
        )
    )


def elapsed(start, end):
    if not start or not end:
        return None
    try:
        delta = (
            datetime.fromisoformat(end) - datetime.fromisoformat(start)
        ).total_seconds()
    except (TypeError, ValueError):
        return None
    return round(delta, 2) if delta >= 0 else None


def difference(first, other):
    """Compare structured campaign facts, or the signed facts text for older deliveries."""
    left = first["offer"] or {}
    right = other["offer"] or {}
    changes = [
        {"field": k, "before": left.get(k), "after": right.get(k)}
        for k in sorted(left.keys() | right.keys())
        if left.get(k) != right.get(k)
    ]
    if not changes and first["facts"] != other["facts"]:
        changes.append(
            {"field": "facts", "before": first["facts"], "after": other["facts"]}
        )
    return changes


def credits(job):
    if job["debit"] is not None:
        return -job["debit"]
    # Successful zero-priced jobs create no debit. A missing paid receipt is unknown.
    if job["state"] == "complete" and job["cost"] == 0:
        return 0
    return None


def version_info(c, tenant, work, number):
    version = c.execute(
        "SELECT created,spec,json_extract(copy,'$.visualEngine') AS visual_engine FROM version WHERE work=? AND n=?",
        (work, number),
    ).fetchone()
    if not version:
        abort(404, description="版本不存在。")
    plan = json.loads(version["spec"]).get("plan", {})
    q = """SELECT j.id,j.created,j.state,j.cost,l.delta AS debit
           FROM job j LEFT JOIN ledger l ON l.tenant=j.tenant AND l.job=j.id WHERE j.tenant=?"""
    job = c.execute(
        q
        + " AND j.work=? AND j.version=? AND j.state='complete' ORDER BY j.rowid DESC LIMIT 1",
        (tenant, work, number),
    ).fetchone()
    info = {
        "version": number,
        "role": "first" if number == 1 else "revision",
        "credits": None,
        "workCredits": None,
        "requestToDeliverySeconds": None,
        "productionSeconds": None,
        "offer": plan.get("merchantOffer"),
        "facts": plan.get("facts") or "",
        "deliveredAt": version["created"],
        "visualEngine": version["visual_engine"],
        "modelCharge": (plan.get("videoProviderReceipt") or {}).get("actualCharge"),
    }
    if not job:
        return info
    info["productionSeconds"] = elapsed(job["created"], version["created"])
    info["workCredits"] = info["credits"] = credits(job)
    run = c.execute(
        "SELECT id,items FROM creative_run WHERE id=? AND tenant=?",
        (plan.get("creationRun"), tenant),
    ).fetchone()
    # Older revisions may carry the parent run ID; it must actually own this job.
    members = {item["job"] for item in json.loads(run["items"])} if run else set()
    if job["id"] not in members:
        return info
    costs = [
        credits(r)
        for r in c.execute(
            q + " AND j.id IN (SELECT value FROM json_each(?))",
            (tenant, dump(sorted(members))),
        )
    ]
    info["credits"] = (
        sum(costs)
        if len(costs) == len(members) and all(x is not None for x in costs)
        else None
    )
    task = c.execute(
        "SELECT created FROM agent_task WHERE tenant=? AND run=?", (tenant, run["id"])
    ).fetchone()
    if task:
        info["requestToDeliverySeconds"] = elapsed(task["created"], version["created"])
    return info


def normalized_answer(value, slots):
    ratings = value.get("ratings")
    if not isinstance(ratings, dict) or set(ratings) != set(slots):
        raise ValueError("请分别评价每个方案能否直接发布。")
    clean = {}
    for slot in slots:
        item = ratings[slot]
        if not isinstance(item, dict) or type(item.get("publish")) is not bool:
            raise ValueError("请选择每份成品是否愿意直接发布。")
        reason = item.get("reason", "")
        if (
            not isinstance(reason, str)
            or len(reason) > 1200
            or (not item["publish"] and not reason.strip())
        ):
            raise ValueError("请用 1–1200 字记录退稿原因。")
        clean[slot] = {"publish": item["publish"], "reason": reason.strip()}
    preference = value.get("preference")
    if len(slots) == 1:
        if preference is not None:
            raise ValueError("首稿反馈只需评价该份成品。")
    else:
        if preference not in ("A", "B", "tie", "neither"):
            raise ValueError("请选择偏好的版本、两版相当或两版都退回。")
    minutes = value.get("merchantEditMinutes")
    if minutes is not None and (
        type(minutes) not in (int, float) or not math.isfinite(minutes) or minutes < 0
    ):
        raise ValueError("自行修改的分钟数需要为零或正数，未知可以留空。")
    return {"preference": preference, "ratings": clean, "merchantEditMinutes": minutes}


def reveal_case(c, row, answer, submitted):
    slots = json.loads(row["slots"])
    versions = {
        s: version_info(c, row["tenant"], row["work"], n) for s, n in slots.items()
    }
    base = min(slots, key=slots.get)
    first = base if slots[base] == 1 else None
    revision = next((s for s in slots if s != base), None)
    changes = difference(versions[base], versions[revision]) if revision else []
    evidence = "retrospective" if first else "no_first_draft"
    if changes and first:
        evidence = "changed_facts"
    if not revision:
        later = c.execute(
            "SELECT MAX(n) FROM version WHERE work=?", (row["work"],)
        ).fetchone()[0]
        if later == 1:
            evidence = "at_first_delivery"
        elif difference(
            versions[first], version_info(c, row["tenant"], row["work"], later)
        ):
            evidence = "changed_facts"
    first_rating = answer["ratings"].get(first, {})
    for version in versions.values():
        version.pop("facts")
    return {
        **answer,
        "baseSlot": base,
        "firstDraftSlot": first,
        "revisionSlot": revision,
        "versions": versions,
        "factChanges": changes,
        "firstDraftEvidence": evidence,
        "firstDraftPublish": first_rating.get("publish"),
        "firstDraftReason": first_rating.get("reason"),
        "reviewSeconds": elapsed(row["created"], submitted),
    }


def case_view(row):
    brief = json.loads(row["brief"])
    slots = json.loads(row["slots"])
    suffix = Path(MEDIA[row["kind"]][0]).suffix
    return {
        "id": row["id"],
        "briefId": brief["id"],
        "brief": {k: brief[k] for k in BRIEF_FIELDS},
        "status": "submitted" if row["answer"] else "open",
        "kind": row["kind"],
        "source": row["source"],
        "options": [
            {
                "slot": slot,
                "url": f"/api/agent/blind-reviews/{row['id']}/media/{slot}{suffix}",
            }
            for slot in slots
        ],
        "reveal": json.loads(row["result"]) if row["result"] else None,
    }


def summary(rows):
    selected = {}
    answered = excluded = 0
    # Latest-first list view is ordered in SQL for display. Analytics uses actual first response.
    for row in sorted(
        (r for r in rows if r["submitted"]),
        key=lambda r: (r["submitted"], r["sequence"]),
    ):
        result = json.loads(row["result"])
        answered += 1
        if result["firstDraftEvidence"] == "no_first_draft":
            continue
        if result["firstDraftEvidence"] == "changed_facts":
            excluded += 1
            continue
        prior = selected.get(row["work"])
        if (
            not prior
            or prior["firstDraftEvidence"] == "retrospective"
            and result["firstDraftEvidence"] == "at_first_delivery"
        ):
            selected[row["work"]] = result
    accepted = sum(r["firstDraftPublish"] for r in selected.values())
    return {
        "issued": len(rows),
        "answered": answered,
        "firstDraftResponses": len(selected),
        "firstDraftPublish": accepted,
        "firstDraftRate": accepted / len(selected) if selected else None,
        "responseRate": answered / len(rows) if rows else None,
        "excludedFactChanged": excluded,
        "retrospectiveFirstDrafts": sum(
            r["firstDraftEvidence"] == "retrospective" for r in selected.values()
        ),
    }


def ensure_schema(c):
    columns = {r[1] for r in c.execute("PRAGMA table_info(merchant_blind_review)")}
    legacy = bool(columns and "base_version" not in columns)
    if legacy:
        # The old UNIQUE key cannot be dropped separately. Preserve ballot IDs,
        # order and signed-off results while expanding the key inside one transaction.
        c.execute("ALTER TABLE merchant_blind_review RENAME TO merchant_blind_review_old")
    c.execute("""CREATE TABLE IF NOT EXISTS merchant_blind_review (
              id TEXT PRIMARY KEY, tenant TEXT NOT NULL, work TEXT NOT NULL,
              base_version INTEGER NOT NULL DEFAULT 1, revision_version INTEGER NOT NULL,
              source TEXT NOT NULL, kind TEXT NOT NULL, brief TEXT NOT NULL, slots TEXT NOT NULL,
              created TEXT NOT NULL, submitted TEXT, answer TEXT, result TEXT,
              UNIQUE(tenant,work,base_version,revision_version,source))""")
    if legacy:
        c.execute("""INSERT INTO merchant_blind_review
                  (rowid,id,tenant,work,revision_version,source,kind,brief,slots,created,submitted,answer,result)
                  SELECT rowid,id,tenant,work,revision_version,source,kind,brief,slots,created,submitted,answer,result
                  FROM merchant_blind_review_old""")
        c.execute("DROP TABLE merchant_blind_review_old")


def register(app, services):
    tenant, owner, body = (services[k] for k in ("reqtenant", "owner", "body"))
    with db(True) as c:
        ensure_schema(c)

    def owned(c, t, case_id):
        row = owner(c, "merchant_blind_review", case_id, t)
        owner(c, "work", row["work"], t)
        return row

    @app.get("/api/agent/blind-briefs")
    def blind_briefs():
        tenant()
        return jsonify(
            briefs=[
                {**b, "creationDraft": creation_draft(b)} for b in briefs().values()
            ]
        )

    @app.get("/api/agent/blind-candidates")
    def blind_candidates():
        t = tenant()
        with db() as c:
            versions = c.execute(
                """SELECT w.id,w.kind,v.n,json_extract(v.copy,'$.title') AS title,
                    json_extract(v.spec,'$.plan.profile.product') AS product,
                    json_extract(v.spec,'$.plan.blindBriefId') AS brief_id FROM work w JOIN version v ON v.work=w.id
                    WHERE w.tenant=? AND w.kind IN ('video','poster','copy')
                    AND NOT EXISTS(SELECT 1 FROM work_trash h WHERE h.work=w.id)
                    ORDER BY w.created DESC,w.rowid DESC,v.n DESC""",
                (t,),
            )
            candidates = {}
            for v in versions:
                candidate = candidates.setdefault(
                    v["id"],
                    {
                        "work": v["id"],
                        "kind": v["kind"],
                        "briefId": v["brief_id"],
                        "title": v["product"] or v["title"] or "已交付作品",
                        "versions": [],
                    },
                )
                candidate["versions"].append(v["n"])
            return jsonify(
                candidates=[
                    {**a, "versions": sorted(a["versions"])}
                    for a in candidates.values()
                    if 1 in a["versions"]
                ]
            )

    @app.get("/api/agent/blind-reviews")
    def blind_index():
        t = tenant()
        with db() as c:
            rows = c.execute(
                """SELECT r.rowid AS sequence,r.* FROM merchant_blind_review r WHERE r.tenant=?
                      AND NOT EXISTS(SELECT 1 FROM work_trash h WHERE h.work=r.work)
                      ORDER BY r.rowid DESC""",
                (t,),
            ).fetchall()
        merchant = [r for r in rows if r["source"] == "merchant"]
        totals = summary(merchant)
        totals["bySector"] = {
            s: summary([r for r in merchant if json.loads(r["brief"])["sector"] == s])
            for s in ("food", "retail", "service")
        }
        reviews = []
        for r in rows:
            b = json.loads(r["brief"])
            reviews.append(
                {
                    "id": r["id"],
                    "briefId": b["id"],
                    "title": b["title"],
                    "sector": b["sector"],
                    "source": r["source"],
                    "status": "submitted" if r["answer"] else "open",
                    "created": r["created"],
                }
            )
        return jsonify(reviews=reviews, summary=totals)

    @app.post("/api/agent/blind-reviews")
    def blind_create():
        t, data = tenant(), body()
        if not isinstance(data, dict):
            abort(400, description="请提交有效的盲评设置。")
        brief_id, work_id, source = (
            data.get("briefId"),
            data.get("work"),
            data.get("source", "merchant"),
        )
        if (
            not isinstance(brief_id, str)
            or brief_id not in briefs()
            or source not in ("merchant", "demo")
        ):
            raise ValueError("请选择有效的简报和评审来源。")
        if not isinstance(work_id, str) or not work_id:
            raise ValueError("请选择已交付的作品。")
        with db(True) as c:
            w = owner(c, "work", work_id, t)
            base = data.get("baseVersion", 1)
            revision = data.get("revisionVersion", w["current"])
            if type(revision) is not int or revision < 1 or w["kind"] not in MEDIA:
                raise ValueError("请选择有效的已交付版本。")
            if type(base) is not int or base < 1 or base > revision or (base == revision and base != 1):
                raise ValueError("请选择比待评版本更早交付的对照版本。")
            old = c.execute(
                """SELECT * FROM merchant_blind_review WHERE tenant=? AND work=?
                            AND base_version=? AND revision_version=? AND source=?""",
                (t, work_id, base, revision, source),
            ).fetchone()
            if old:
                if json.loads(old["brief"])["id"] != brief_id:
                    abort(409, description="该版本已关联另一份评审简报。")
                return jsonify(case_view(old))
            pair = [1] if revision == 1 else [base, revision]
            for n in pair:
                if not c.execute(
                    "SELECT 1 FROM version WHERE work=? AND n=?", (work_id, n)
                ).fetchone():
                    abort(404, description="所选版本未交付。")
                path = DATA / t / "works" / work_id / str(n) / MEDIA[w["kind"]][0]
                if not path.is_file():
                    abort(409, description="成品文件暂不可用，请恢复后重试。")
            if len(pair) > 1 and secrets.randbelow(2):
                pair.reverse()
            slots = dict(zip(("A", "B"), pair))
            case_id = ident()
            c.execute(
                """INSERT INTO merchant_blind_review(id,tenant,work,base_version,revision_version,source,kind,brief,slots,created)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    case_id,
                    t,
                    work_id,
                    base,
                    revision,
                    source,
                    w["kind"],
                    dump(briefs()[brief_id]),
                    dump(slots),
                    now(),
                ),
            )
            return jsonify(case_view(owned(c, t, case_id)))

    @app.get("/api/agent/blind-reviews/<case_id>")
    def blind_detail(case_id):
        t = tenant()
        with db() as c:
            return jsonify(case_view(owned(c, t, case_id)))

    @app.get("/api/agent/blind-reviews/<case_id>/media/<slot>.<extension>")
    def blind_media(case_id, slot, extension):
        t = tenant()
        with db() as c:
            row = owned(c, t, case_id)
            version = json.loads(row["slots"]).get(slot)
            name, mime = MEDIA[row["kind"]]
            if not version or Path(name).suffix != "." + extension:
                abort(404)
            path = DATA / t / "works" / row["work"] / str(version) / name
        if not path.is_file():
            abort(404)
        response = send_file(
            path,
            mimetype=mime,
            download_name=f"{slot}.{extension}",
            conditional=True,
            etag=False,
            last_modified=0,
        )
        response.headers.pop("Last-Modified", None)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.post("/api/agent/blind-reviews/<case_id>/answer")
    def blind_answer(case_id):
        t, payload = tenant(), body()
        if not isinstance(payload, dict):
            abort(400, description="请提交有效的评审反馈。")
        with db(True) as c:
            row = owned(c, t, case_id)
            try:
                answer = normalized_answer(payload, json.loads(row["slots"]))
            except ValueError:
                if row["answer"]:
                    abort(409, description="反馈已锁定，请查看已提交的记录。")
                raise
            if row["answer"]:
                if json.loads(row["answer"]) != answer:
                    abort(409, description="反馈已锁定，请查看已提交的记录。")
                return jsonify(case_view(row))
            if len(answer["ratings"]) == 2:
                accepted = {s for s, r in answer["ratings"].items() if r["publish"]}
                choices = accepted | ({"tie"} if len(accepted) == 2 else set())
                if answer["preference"] not in (choices or {"neither"}):
                    raise ValueError(
                        "请从愿意直接发布的作品中选择。两版都需要修改时，请选两版都退回。"
                    )
            submitted = now()
            result = reveal_case(c, row, answer, submitted)
            c.execute(
                "UPDATE merchant_blind_review SET submitted=?,answer=?,result=? WHERE id=?",
                (submitted, dump(answer), dump(result), case_id),
            )
            return jsonify(case_view(owned(c, t, case_id)))
