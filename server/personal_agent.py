"""Merchant-facing conversation orchestration. Only a bound quote approval can start jobs."""

import datetime as dt
import json
import os
import re
import time

from flask import abort, jsonify, request

from . import agent_dialogue, agent_planner as planner, context_memory, copy_choices, wallet
from .agent_store import (
    check_revision,
    enabled,
    event,
    initialize,
    invalidate_summaries,
    memory_rows,
    message,
    metrics as metrics,
    new_conversation,
    preferences,
    project_for,
    run_status,
)
from .campaign import storyboard
from .store import db, dump, ident, now


def checked_text(value, limit, label):
    if not isinstance(value, str) or not 0 < len(value.strip()) <= limit:
        raise ValueError(f"请填写{label}，最多 {limit} 字。")
    return value.strip()


def suggestion_list(c, services, tenant, cid, automatic=False):
    today = dt.date.today()
    pref = preferences(c, tenant)
    if automatic and (
        not pref["weeks"]
        or pref["last_sent"]
        and (today - dt.date.fromisoformat(pref["last_sent"])).days < 7 * pref["weeks"]
    ):
        return
    profile = json.loads(
        c.execute("SELECT profile FROM merchant WHERE id=?", (tenant,)).fetchone()[0]
    )
    items = services["weekly"](c, tenant, profile, services["history"](c, tenant))[:3]
    message(c, cid, "assistant", "topics", {"items": items})
    c.execute(
        """INSERT INTO agent_preferences VALUES(?,?,?) ON CONFLICT(tenant) DO UPDATE SET last_sent=excluded.last_sent""",
        (tenant, pref["weeks"], today.isoformat()),
    )


def select_copy(c, task, index):
    options = json.loads(task["options"])
    if (
        task["status"] not in ("waiting_copy", "quoted")
        or task["run"]
        or type(index) is not int
        or not 0 <= index < len(options)
    ):
        raise ValueError("请从当前任务的候选文案中选择。")
    c.execute(
        "UPDATE agent_task SET locked=?,status='quoted',revision=revision+1 WHERE id=?",
        (dump(options[index]), task["id"]),
    )
    event(
        c,
        dict(id=task["id"], revision=task["revision"] + 1),
        "quoted",
        {"choice": index, "cost": task["cost"]},
    )


def build_plan(services, tid, tenant):
    owner = services["owner"]
    with db() as c:
        task = owner(c, "agent_task", tid, tenant)
        if task["status"] != "planning":
            return
        conv = owner(c, "conversation", task["conversation"], tenant)
        values = json.loads(task["input"])
        try:
            if values.get("workRef"):
                revision, revision_brief, locked = planner.revision_plan(
                    services, c, tenant, values
                )
                result = dict(ready=True, cost=revision["cost"])
            else:
                result = planner.plan_task(services, c, tenant, conv["project"], values)
                locked = json.loads(task["locked"]) if task["locked"] else None
                if result["ready"] and values.get("ownCopy"):
                    locked = planner.provided_copy(values["ownCopy"], result)
        except ValueError as exc:
            result = dict(ready=False, message=str(exc))
    with db(True) as c:
        current = owner(c, "agent_task", tid, tenant)
        if current["revision"] != task["revision"] or current["status"] != "planning":
            return
        if not result["ready"]:
            note = (result.get("questions") or [result["message"]])[0]
            c.execute(
                "UPDATE agent_task SET status='waiting_input',note=? WHERE id=?",
                (note, tid),
            )
            event(c, task, "waiting_input", {"text": note})
            return
        if values.get("workRef"):
            c.execute(
                """UPDATE agent_task SET status='quoted',quote=?,quote_id=?,cost=?,brief=?,locked=?,note='' WHERE id=?""",
                (
                    revision["quote"],
                    ident(),
                    result["cost"],
                    dump(revision_brief),
                    dump(locked),
                    tid,
                ),
            )
            event(
                c, task, "quoted", {"cost": result["cost"], "source": values["workRef"]}
            )
            return
        quote = services["quotes"].dumps(
            dict(autoCreation=True, tenant=tenant, **result)
        )
        brief = {
            **result["shared"],
            "deliveries": [i["label"] for i in result["items"]],
            "pricing": [i["spec"]["pricingSnapshot"] for i in result["items"]],
        }
        if values["kind"] == "video":
            video = next(
                i["spec"] for i in result["items"] if i["spec"]["kind"] == "video"
            )
            brief["storyboard"] = storyboard(
                video["plan"], locked or video["replacement"]
            )
        status = (
            {"poster": "waiting_copy", "video": "waiting_script"}.get(
                values["kind"], "quoted"
            )
            if not locked
            else "quoted"
        )
        c.execute(
            """UPDATE agent_task SET status=?,quote=?,quote_id=?,cost=?,brief=?,locked=?,note='' WHERE id=?""",
            (
                status,
                quote,
                ident(),
                result["cost"],
                dump(brief),
                dump(locked) if locked else None,
                tid,
            ),
        )
        event(c, task, status, {"cost": result["cost"]})


def task_view(c, services, row):
    data = json.loads(row["input"])
    brief = json.loads(row["brief"])
    view = dict(
        id=row["id"],
        revision=row["revision"],
        status=run_status(c, row),
        kind=data["kind"],
        request=data["brief"],
        ratio=data["ratio"],
        imageCount=data.get("imageCount", 1),
        duration=data.get("duration", 15),
        note=row["note"],
        cost=row["cost"],
        quoteId=row["quote_id"],
        options=[
            {k: v.get(k, "") for k in ("title", "body", "cta")}
            for v in json.loads(row["options"])
        ],
        concept=brief.get("concept", ""),
        deliveries=brief.get("deliveries", []),
        facts=brief.get("facts", []),
        recalledMemories=brief.get("recalledMemories", []),
        shortOptions=brief.get("shortOptions", []),
        workRef=data.get("workRef"),
        storyboard=brief.get("storyboard", []),
        asset=data.get("asset", ""),
    )
    if row["locked"]:
        chosen = json.loads(row["locked"])
        view["locked"] = {k: chosen.get(k, "") for k in ("title", "body", "cta")}
    if row["run"]:
        run = services["owner"](c, "creative_run", row["run"], row["tenant"])
        result = services["creation_details"](c, run)
        keys = (
            "job",
            "label",
            "cost",
            "state",
            "stage",
            "error",
            "kind",
            "work",
            "preview",
            "video",
            "text",
            "download",
        )
        items = []
        for i in result["items"]:
            entry = {k: i.get(k) for k in keys}
            if i.get("state") == "complete" and i.get("job"):
                jrow = c.execute("SELECT version FROM job WHERE id=?", (i["job"],)).fetchone()
                if jrow:
                    entry["version"] = jrow["version"]
            items.append(entry)
        view["items"] = items
        view["download"] = result["download"] if result["complete"] else None
    return view


def register(app, services):
    initialize()
    owner, tenant, body = (services[k] for k in ("owner", "reqtenant", "body"))

    @app.before_request
    def agent_rollout():
        if (
            request.path.startswith("/api/agent/")
            and request.method == "POST"
            and not request.path.endswith("/cancel")
            and not enabled(tenant())
        ):
            abort(403, description="当前工作空间使用原创作台。")

    def conversation(c, cid, t):
        row = owner(c, "conversation", cid, t)
        if row["archived"]:
            abort(404, description="对话已移入历史归档。")
        return row

    def detail(c, cid, t):
        row = conversation(c, cid, t)
        turns = [
            dict(
                seq=m["seq"],
                role=m["role"],
                kind=m["kind"],
                created=m["created"],
                **json.loads(m["content"]),
            )
            for m in c.execute(
                "SELECT * FROM agent_message WHERE conversation=? ORDER BY seq", (cid,)
            )
        ]
        tasks = [
            task_view(c, services, r)
            for r in c.execute(
                "SELECT * FROM agent_task WHERE conversation=? AND tenant=? ORDER BY rowid",
                (cid, t),
            )
        ]
        candidates = [
            r
            for r in memory_rows(c, t, row["project"], include_candidates=True)
            if r["status"] == "candidate"
        ]
        summary_row = c.execute(
            "SELECT up_to_seq,summary,updated FROM agent_context_summary WHERE conversation=? AND tenant=?",
            (cid, t),
        ).fetchone()
        return dict(
            id=cid,
            title=row["title"],
            project=row["project"],
            messages=turns,
            tasks=tasks,
            candidates=candidates,
            contextSummary=dict(summary_row) if summary_row else None,
        )

    @app.get("/api/agent")
    def agent_home():
        t = tenant()
        with db() as c:
            pending = c.execute(
                """SELECT a.id AS task, a.conversation, json_extract(a.input,'$.brief') AS title,
                          a.status, a.run, a.tenant, CASE WHEN a.status='quoted' THEN a.cost END AS cost
                   FROM agent_task a JOIN conversation c ON c.id=a.conversation
                   WHERE a.tenant=? AND c.tenant=? AND c.archived=0 AND (
                     (a.run IS NULL AND a.status IN ('planning','waiting_input','waiting_copy','waiting_script','quoted'))
                     OR (a.status!='cancelled' AND EXISTS (
                       SELECT 1 FROM creative_run r, json_each(r.items) i JOIN job j
                         ON j.id=json_extract(i.value,'$.job')
                       WHERE r.id=a.run AND r.tenant=a.tenant AND j.state IN ('queued','running'))))
                   ORDER BY (a.run IS NULL AND a.status!='planning') DESC,
                            COALESCE((SELECT MAX(seq) FROM agent_event WHERE task=a.id),0) DESC,
                            a.rowid DESC LIMIT 1""",
                (t, t),
            ).fetchone()
            convs = []
            for r in c.execute(
                """SELECT id,title,project,created FROM conversation
                WHERE tenant=? AND archived=0 ORDER BY created DESC,rowid DESC""",
                (t,),
            ):
                item = dict(r)
                latest = c.execute(
                    "SELECT * FROM agent_task WHERE conversation=? AND tenant=? ORDER BY rowid DESC LIMIT 1",
                    (r["id"], t),
                ).fetchone()
                st = run_status(c, latest) if latest else None
                item["activeStatus"] = (
                    st
                    if st
                    in (
                        "waiting_input",
                        "waiting_copy",
                        "waiting_script",
                        "quoted",
                        "queued",
                        "running",
                        "reviewing",
                    )
                    else None
                )
                convs.append(item)
            cand_count = c.execute(
                "SELECT COUNT(*) FROM agent_memory WHERE tenant=? AND status='candidate'",
                (t,),
            ).fetchone()[0]
            return jsonify(
                workspace=t,
                pending={
                    **{key: pending[key] for key in ("task", "conversation", "title", "cost")},
                    "status": run_status(c, pending),
                } if pending else None,
                conversations=convs,
                projects=[
                    dict(r)
                    for r in c.execute(
                        "SELECT id,title FROM agent_project WHERE tenant=? ORDER BY rowid DESC",
                        (t,),
                    )
                ],
                weeks=preferences(c, t)["weeks"],
                candidateCount=cand_count,
            )

    @app.get("/api/agent/capabilities")
    def agent_capabilities():
        tenant()
        with db() as c:
            return jsonify(capabilities=planner.capability_registry(c))

    @app.get("/api/agent/conversations/<cid>/context")
    def agent_context(cid):
        t = tenant()
        q = request.args.get("q", "")
        with db() as c:
            conv = conversation(c, cid, t)
            return jsonify(
                context_memory.build_context_packet(c, t, conv, question=q, write_summary=False)
            )

    @app.post("/api/agent/projects")
    def agent_project():
        t, title, pid = (
            tenant(),
            checked_text(body().get("title"), 60, "项目名称"),
            ident(),
        )
        with db(True) as c:
            c.execute("INSERT INTO agent_project VALUES(?,?,?)", (pid, t, title))
        return jsonify(id=pid, title=title)

    @app.post("/api/agent/preferences")
    def agent_preferences():
        t, weeks = tenant(), body().get("weeks")
        if type(weeks) is not int or not 0 <= weeks <= 4:
            raise ValueError("请选择推荐间隔。")
        with db(True) as c:
            c.execute(
                """INSERT INTO agent_preferences VALUES(?,?,NULL) ON CONFLICT(tenant)
                DO UPDATE SET weeks=excluded.weeks""",
                (t, weeks),
            )
        return jsonify(weeks=weeks)

    @app.post("/api/agent/conversations")
    def agent_create():
        t, v = tenant(), body()
        with db(True) as c:
            cid = new_conversation(c, t, project_for(c, t, v.get("project")))
            suggestion_list(c, services, t, cid, automatic=True)
            return jsonify(detail(c, cid, t))

    @app.post("/api/agent/conversations/<cid>/visit")
    def agent_visit(cid):
        t = tenant()
        with db(True) as c:
            conversation(c, cid, t)
            suggestion_list(c, services, t, cid, automatic=True)
            return jsonify(detail(c, cid, t))

    @app.route("/api/agent/conversations/<cid>", methods=["GET", "DELETE"])
    def agent_conversation(cid):
        t = tenant()
        with db(request.method == "DELETE") as c:
            conversation(c, cid, t)
            if request.method == "DELETE":
                c.execute("UPDATE conversation SET archived=1 WHERE id=?", (cid,))
                return jsonify(archived=True)
            return jsonify(detail(c, cid, t))

    @app.get("/api/agent/conversations/<cid>/messages")
    def agent_messages(cid):
        t = tenant()
        with db() as c:
            conversation(c, cid, t)
            after = request.args.get("after", 0, type=int)
            return jsonify(
                messages=[
                    dict(
                        seq=r["seq"],
                        role=r["role"],
                        kind=r["kind"],
                        **json.loads(r["content"]),
                    )
                    for r in c.execute(
                        "SELECT * FROM agent_message WHERE conversation=? AND seq>? ORDER BY seq LIMIT 200",
                        (cid, after),
                    )
                ]
            )

    def _checked_expiry(raw):
        if raw in (None, ""):
            return None
        if not isinstance(raw, str) or len(raw) != 10:
            raise ValueError("有效期格式应为 YYYY-MM-DD。")
        try:
            dt.date.fromisoformat(raw)
        except ValueError:
            raise ValueError("有效期格式应为 YYYY-MM-DD。")
        return raw

    @app.route("/api/agent/memory", methods=["GET", "POST"])
    def agent_memory():
        t, v = tenant(), body()
        with db(request.method == "POST") as c:
            project = project_for(c, t, v.get("project") or request.args.get("project"))
            if request.method == "GET":
                return jsonify(entries=memory_rows(c, t, project))
            name = checked_text(v.get("name"), 60, "记忆名称")
            value = checked_text(v.get("value"), 240, "记忆内容")
            kind = v.get("kind", "fact")
            if kind not in ("fact", "preference", "asset"):
                raise ValueError("记忆类别无效。")
            if kind == "asset":
                owner(c, "asset", value, t)
            expires_at = _checked_expiry(v.get("expiresAt"))
            if c.execute(
                "SELECT 1 FROM agent_memory WHERE tenant=? AND project=? AND name=?",
                (t, project or "", name),
            ).fetchone():
                abort(409, description="已有同名记忆，请打开原条目确认修改。")
            mid = ident()
            c.execute(
                """INSERT INTO agent_memory(id,tenant,project,name,value,kind,active,version,updated,status,expires_at)
                   VALUES(?,?,?,?,?,?,1,1,?,'confirmed',?)""",
                (mid, t, project or "", name, value, kind, now(), expires_at),
            )
            invalidate_summaries(c, t, project)
            return jsonify(id=mid, version=1)

    @app.route("/api/agent/memory/<mid>", methods=["GET", "PATCH", "DELETE"])
    def agent_memory_item(mid):
        t, v = tenant(), body()
        with db(request.method != "GET") as c:
            row = owner(c, "agent_memory", mid, t)
            if request.method == "GET":
                return jsonify(dict(row))
            if v.get("version") != row["version"]:
                abort(409, description="记忆已更新，请重新查看。")
            if request.method == "DELETE":
                c.execute("DELETE FROM agent_memory WHERE id=?", (mid,))
                invalidate_summaries(c, t, row["project"] or None)
            else:
                value = checked_text(v.get("value", row["value"]), 240, "记忆内容")
                if row["kind"] == "asset":
                    owner(c, "asset", value, t)
                active = v.get("active", bool(row["active"]))
                if type(active) is not bool:
                    raise ValueError("请选择是否启用。")
                status = v.get("status", row["status"] or "confirmed")
                if status not in ("candidate", "confirmed", "expired", "revoked"):
                    raise ValueError("记忆状态无效。")
                expires_at = (
                    _checked_expiry(v["expiresAt"])
                    if "expiresAt" in v
                    else row["expires_at"]
                )
                c.execute(
                    """UPDATE agent_memory SET value=?,active=?,status=?,expires_at=?,
                       version=version+1,updated=? WHERE id=?""",
                    (value, active, status, expires_at, now(), mid),
                )
                invalidate_summaries(c, t, row["project"] or None)
            return jsonify(ok=True)

    @app.post("/api/agent/memory/<mid>/confirm")
    def agent_memory_confirm(mid):
        t, v = tenant(), body()
        with db(True) as c:
            row = owner(c, "agent_memory", mid, t)
            if v.get("version") is not None and v.get("version") != row["version"]:
                abort(409, description="记忆已更新，请重新查看。")
            c.execute(
                """UPDATE agent_memory SET status='confirmed',active=1,version=version+1,updated=?
                   WHERE id=?""",
                (now(), mid),
            )
            invalidate_summaries(c, t, row["project"] or None)
            return jsonify(ok=True, id=mid, version=row["version"] + 1)

    @app.post("/api/agent/memory/<mid>/dismiss")
    def agent_memory_dismiss(mid):
        t, v = tenant(), body()
        with db(True) as c:
            row = owner(c, "agent_memory", mid, t)
            if v.get("version") is not None and v.get("version") != row["version"]:
                abort(409, description="记忆已更新，请重新查看。")
            c.execute("DELETE FROM agent_memory WHERE id=?", (mid,))
            invalidate_summaries(c, t, row["project"] or None)
            return jsonify(ok=True)

    def answer(c, t, cid, v):
        conv = conversation(c, cid, t)
        text = checked_text(v.get("text"), 1200, "消息")
        key = checked_text(v.get("requestKey"), 90, "请求标识")
        old = c.execute(
            "SELECT content FROM agent_message WHERE conversation=? AND request_key=?",
            (cid, key),
        ).fetchone()
        if old:
            saved = json.loads(old[0])
            return saved.get("target", cid), saved.get("prepare") or saved.get(
                "discussion"
            )
        target = cid
        action = v.get("action", "send")
        if action not in (
            "send",
            "new",
            "here",
            "branch",
            "revise",
            "topics",
            "select",
            "refresh",
        ):
            raise ValueError("消息操作无效。")
        options = v.get("options", {})
        if not isinstance(options, dict):
            raise ValueError("创作选项格式无效。")
        task = None
        if v.get("task"):
            task = owner(c, "agent_task", v["task"], t)
            if task["conversation"] != cid:
                abort(404)
            check_revision(task, v.get("revision"))
        else:
            task = c.execute(
                "SELECT * FROM agent_task WHERE conversation=? ORDER BY rowid DESC LIMIT 1",
                (cid,),
            ).fetchone()
        ordinal = planner.ordinal(text)
        idx = v.get("index", ordinal)
        last = c.execute(
            "SELECT * FROM agent_message WHERE conversation=? AND role='assistant' ORDER BY seq DESC LIMIT 1",
            (cid,),
        ).fetchone()

        def record(**extra):
            asset = options.get("asset")
            if asset:
                if not isinstance(asset, str):
                    raise ValueError("素材标识无效。")
                owner(c, "asset", asset, t)
                extra["asset"] = asset
            message(c, cid, "user", "text", dict(text=text, **extra), key)
            return c.execute("SELECT last_insert_rowid()").fetchone()[0]

        command = text.rstrip("，,。.!！?？ ")
        if action == "send" and (
            context_memory.EXPLICIT_REMEMBER.match(text.strip())
            or context_memory.EXPLICIT_FORGET.match(text.strip())
        ):
            user_seq = record()
            reply_text = context_memory.handle_memory_command(
                c, t, conv["project"], text, source_seq=user_seq
            )
            if reply_text:
                message(c, cid, "assistant", "text", {"text": reply_text})
                return cid, None
        if (action == "send" and task and task["status"] == "quoted"
                and re.fullmatch(r"(?:请|帮我)?(?:确认制作|开始制作|确认扣积分|确认扣款|确认)", command)):
            record()
            message(c, cid, "assistant", "text",
                    {"text": f"本次制作需要 {task['cost']} 积分。请在任务卡上点「确认制作」。"})
            return cid, None
        if action == "send" and (
            agent_dialogue.DISCUSS.search(text) or command in ("你好", "您好", "在吗")
        ):
            user_seq = record()
            if command in ("你好", "您好", "在吗"):
                message(
                    c,
                    cid,
                    "assistant",
                    "text",
                    {"text": "你好！今天想为店里推广什么？"},
                )
                context_memory.compact_conversation(c, t, cid)
                return cid, None
            context_memory.propose_candidates(c, t, conv["project"], text, source_seq=user_seq)
            message(
                c,
                cid,
                "assistant",
                "discussion",
                {"question": text, "text": "正在整理建议…"},
            )
            seq = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            c.execute(
                "UPDATE agent_message SET content=? WHERE conversation=? AND request_key=?",
                (dump({"text": text, "discussion": seq}), cid, key),
            )
            return cid, seq
        if action == "topics" or command in ("本周推荐", "本周灵感", "推荐几个主题"):
            record()
            suggestion_list(c, services, t, cid)
            return cid, None
        if action == "select" or (
            ordinal is not None
            and task
            and (
                task["status"] == "waiting_copy"
                or (task["status"] == "quoted" and json.loads(task["options"]))
            )
            and last
            and last["kind"] != "topics"
        ):
            if not task:
                raise ValueError("请先选择任务。")
            select_copy(c, task, idx)
            record()
            message(
                c,
                cid,
                "assistant",
                "text",
                {"text": "文案已选定，请查看任务卡上的报价。"},
            )
            return cid, None
        if ordinal is not None and last and last["kind"] == "topics":
            items = json.loads(last["content"])["items"]
            if ordinal >= len(items):
                raise ValueError("请从上方推荐主题中选择。")
            item = items[ordinal]
            options = {**options, "topicId": item["topicId"]}
            brief = item["brief"]
            action = "new"
        else:
            brief = text
        if action == "send" and re.search(
            r"^(?:查看|看看|告诉我|复述|现在|我选的|刚才选的).*(?:文案|进度|规格|任务|画幅|选了什么)|^(?:进度|任务状态|选的文案)[？?]?$",
            text,
        ):
            record()
            if task:
                card = task_view(c, services, task)
                answer_text = " · ".join(
                    [
                        planner.KINDS[card["kind"]],
                        ":".join(map(str, planner.RATIOS[card["ratio"]])),
                    ]
                    + card["deliveries"]
                )
                if card.get("locked"):
                    answer_text += "\n" + "\n".join(
                        s for s in card["locked"].values() if s
                    )
                message(
                    c,
                    cid,
                    "assistant",
                    "text",
                    {"text": answer_text + "\n制作状态见本对话的任务卡。"},
                )
            else:
                message(
                    c, cid, "assistant", "text", {"text": "这段对话还没有创作任务。"}
                )
            return cid, None
        if action == "send" and re.search(
            r"你.{0,3}记得|店铺资料|有哪些记忆|记住了什么|项目资料|商家资料", text
        ):
            record()
            values, profile = planner.assemble(c, t, conv["project"], {})
            lines = [
                str(profile[k])
                for k in ("name", "industry", "product", "facts", "tone", "city")
                if profile.get(k)
            ]
            if values.get("asset"):
                lines.append("已关联项目或商家的共享素材。")
            message(
                c,
                cid,
                "assistant",
                "text",
                {
                    "text": "\n".join(lines)
                    or "还没有已确认的资料。可以在「助理记忆」中添加。"
                },
            )
            return cid, None
        if action == "send" and (
            re.search(r"昨天那张|上次那张|之前那张|以前那张", text)
            or (not task and "照这个再做" in text)
        ):
            record()
            matches = [
                dict(id=r["id"], version=r["current"], label=r["label"])
                for r in c.execute(
                    """SELECT w.id,w.current,COALESCE(NULLIF(json_extract(v.copy,'$.title'),''),'历史作品') label
                   FROM work w JOIN version v ON v.work=w.id AND v.n=w.current WHERE w.tenant=?
                   AND NOT EXISTS(SELECT 1 FROM work_trash h WHERE h.work=w.id) ORDER BY w.created DESC,w.rowid DESC LIMIT 12""",
                    (t,),
                )
            ]
            message(
                c,
                cid,
                "assistant",
                "pick_work",
                {
                    "text": "选出要沿用的作品，再告诉我想改哪里。"
                    if matches
                    else "还没有已保存的作品。",
                    "instruction": text,
                    "items": matches,
                    "needsInstruction": True,
                },
            )
            return cid, None
        if action == "send" and re.fullmatch(
            r"再来一个[。！!？?]?|再做一个[。！!？?]?", text
        ):
            record()
            message(
                c,
                cid,
                "assistant",
                "text",
                {
                    "text": "想沿用哪份作品？可以打开对应成品的「照这个再做」，也可以告诉我新的创作主题。"
                },
            )
            return cid, None
        previous = json.loads(task["input"]) if task else {}
        waiting = task and not task["run"] and task["status"] != "cancelled"
        kind = planner.explicit_kind(text)
        switch = previous and (
            kind
            and kind != previous["kind"]
            or any(a in text and a not in previous["brief"] for a in planner.ANGLES)
        )
        if (
            action == "send"
            and switch
            and not ordinal
            and not re.search(r"改成|改为|换成", text)
        ):
            record()
            message(c, cid, "assistant", "switch", {"text": text, "options": options})
            return cid, None
        if action == "branch":
            target = new_conversation(c, t, conv["project"])
        revise = action in ("revise", "refresh") or (action == "send" and waiting)
        if revise and not waiting:
            abort(409, description="这份任务已提交或取消，请新建任务。")
        if (
            revise
            and task["status"] == "waiting_copy"
            and planner.DELEGATE.search(text)
            and json.loads(task["options"])
        ):
            select_copy(c, task, 0)
            record()
            message(
                c,
                cid,
                "assistant",
                "text",
                {"text": "已采用第一组复核文案。请确认制作积分。"},
            )
            return cid, None
        ref = v.get("workRef")
        if (
            not ref
            and action == "send"
            and task
            and task["run"]
            and re.search(
                r"换一张|换张图|换图|太长|短一点|精简|缩短|换个创意|改[成为]|修改|排版|照这个再做",
                text,
            )
        ):
            items = [
                i
                for i in task_view(c, services, task).get("items", [])
                if i["state"] == "complete"
            ]
            visuals = [i for i in items if i["kind"] != "copy"]
            targets = visuals or items
            if len(targets) == 1:
                chosen = targets[0]
                job = owner(c, "job", chosen["job"], t)
                ref = dict(id=chosen["work"], version=job["version"])
            else:
                record()
                message(
                    c,
                    cid,
                    "assistant",
                    "pick_work",
                    {
                        "text": "想改哪份作品？请选定成品。",
                        "instruction": text,
                        "items": [
                            dict(
                                id=i["work"],
                                label=i["label"],
                                version=owner(c, "job", i["job"], t)["version"],
                            )
                            for i in targets
                        ],
                    },
                )
                return cid, None
        new_locked = task["locked"] if revise and task else None
        if ref:
            if not isinstance(ref, dict) or type(ref.get("version")) is not int:
                raise ValueError("请选择原作品及版本。")
            original = owner(c, "work", ref.get("id"), t)
            base = c.execute(
                "SELECT spec FROM version WHERE work=? AND n=?",
                (original["id"], ref["version"]),
            ).fetchone()
            if not base:
                abort(404)
            spec = json.loads(base[0])
            values = dict(
                brief=text,
                kind=original["kind"],
                ratio=spec["ratio"],
                workRef={"id": original["id"], "version": ref["version"]},
                edit=planner.revision_request(text, ref["version"]),
            )
            revise = False
        elif action == "refresh":
            values = previous
        elif revise and previous.get("workRef"):
            values = {
                **previous,
                "brief": brief,
                "edit": planner.revision_request(brief, previous["workRef"]["version"]),
            }
        else:
            locked = json.loads(task["locked"]) if revise and task["locked"] else None
            corrected = revise and planner.correct_price(previous, locked, brief)
            if corrected and locked:
                new_locked = dump(locked)
            values = planner.task_input(
                "" if corrected else brief, options, previous if revise else None
            )
        tid = task["id"] if revise else ident()
        user_seq = record(target=target, prepare=tid)
        if action in ("send", "new", "here"):
            context_memory.propose_candidates(c, t, conv["project"], text, source_seq=user_seq)
        context_memory.compact_conversation(c, t, target)
        if target != cid:
            message(c, target, "user", "text", {"text": text})
        if revise:
            # A new quote is required for every changed spec. Keep the selected copy across layout changes.
            c.execute(
                """UPDATE agent_task SET revision=revision+1,status='planning',input=?,quote=NULL,quote_id=NULL,
                cost=NULL,options='[]',note='',brief='{}',locked=? WHERE id=?""",
                (dump(values), new_locked, tid),
            )
        else:
            c.execute(
                "INSERT INTO agent_task(id,tenant,conversation,revision,status,input,created) VALUES(?,?,?,1,'planning',?,?)",
                (tid, t, target, dump(values), now()),
            )
            c.execute(
                "UPDATE conversation SET title=? WHERE id=? AND title='新对话'",
                (brief[:28], target),
            )
        message(c, target, "assistant", "task", {"task": tid})
        event(c, owner(c, "agent_task", tid, t), "planning", {})
        return target, tid

    @app.post("/api/agent/conversations/<cid>/messages")
    def agent_send(cid):
        t, v = tenant(), body()
        with db(True) as c:
            target, tid = answer(c, t, cid, v)
        if isinstance(tid, int):
            agent_dialogue.respond(services, t, target, tid)
        elif tid:
            build_plan(services, tid, t)
        with db() as c:
            return jsonify(detail(c, target, t))

    @app.post("/api/agent/tasks/<tid>/prepare")
    def agent_prepare(tid):
        t = tenant()
        build_plan(services, tid, t)
        with db() as c:
            return jsonify(task_view(c, services, owner(c, "agent_task", tid, t)))

    @app.post("/api/agent/tasks/<tid>/options")
    def agent_options(tid):
        t, v = tenant(), body()
        token = ident()
        with db(True) as c:
            task = owner(c, "agent_task", tid, t)
            check_revision(task, v.get("revision"))
            if task["status"] not in ("waiting_copy", "waiting_script"):
                abort(409, description="任务已离开选稿阶段。")
            if json.loads(task["options"]):
                return jsonify(task_view(c, services, task))
            # Candidate generation is free of merchant charges. Approval checks quote expiry separately.
            plan = services["quotes"].loads(task["quote"])
            script = task["status"] == "waiting_script"
            kind = "video" if script else "poster"
            spec = next(i["spec"] for i in plan["items"] if i["spec"]["kind"] == kind)
            lease = c.execute(
                "SELECT revision,expires FROM agent_option_lease WHERE task=?", (tid,)
            ).fetchone()
            if (
                lease
                and lease["revision"] == task["revision"]
                and lease["expires"] > time.time()
            ):
                abort(409, description="正在生成这一版候选文案，请稍候查看。")
            c.execute(
                "INSERT OR REPLACE INTO agent_option_lease VALUES(?,?,?,?)",
                (tid, task["revision"], token, time.time() + 600),
            )
        try:
            if script:
                draft = services["generate_copy"](spec["plan"])
                if draft.get("reviewFlag"):
                    raise ValueError(
                        draft.get("callError")
                        or draft.get("revisionNote")
                        or "脚本未通过复核，请补充商品信息后重试。"
                    )
                draft = {**spec["replacement"], **draft}
                if longer := services["long_form"](spec["plan"], draft):
                    draft["longForm"] = longer
                outline = storyboard(spec["plan"], draft)
            else:
                options = copy_choices.write_options(spec, t)
        except Exception:
            with db(True) as c:
                c.execute(
                    "DELETE FROM agent_option_lease WHERE task=? AND token=?",
                    (tid, token),
                )
            raise
        with db(True) as c:
            if not c.execute(
                "DELETE FROM agent_option_lease WHERE task=? AND token=?", (tid, token)
            ).rowcount:
                abort(409, description="候选请求已更新，请查看当前文案。")
            current = owner(c, "agent_task", tid, t)
            check_revision(current, v.get("revision"))
            if current["status"] != task["status"]:
                abort(409, description="任务已更新。")
            if script:
                brief = {**json.loads(task["brief"]), "storyboard": outline}
                c.execute(
                    "UPDATE agent_task SET locked=?,brief=?,status='quoted',revision=revision+1 WHERE id=?",
                    (dump(draft), dump(brief), tid),
                )
                event(
                    c,
                    owner(c, "agent_task", tid, t),
                    "quoted",
                    {"cost": task["cost"], "script": True},
                )
                return jsonify(task_view(c, services, owner(c, "agent_task", tid, t)))
            if current["status"] != "waiting_copy":
                abort(409, description="任务已更新。")
            if not json.loads(current["options"]):
                c.execute(
                    "UPDATE agent_task SET options=? WHERE id=?", (dump(options), tid)
                )
                event(c, current, "copy_options", {"count": len(options)})
                if json.loads(current["input"]).get("delegate"):
                    select_copy(c, owner(c, "agent_task", tid, t), 0)
            return jsonify(task_view(c, services, owner(c, "agent_task", tid, t)))

    @app.post("/api/agent/tasks/<tid>/approve")
    def agent_approve(tid):
        t, v = tenant(), body()
        key = checked_text(v.get("requestKey"), 90, "确认标识")

        def validate(task):
            check_revision(task, v.get("revision"))
            if (
                v.get("approvalType") != "production"
                or task["quote_id"] != v.get("quoteId")
                or type(v.get("confirmedCost")) is not int
                or task["cost"] != v["confirmedCost"]
            ):
                abort(409, description="报价已变动，请按当前任务卡确认。")
            if task["run"] and task["approval_key"] == key:
                return
            if task["status"] != "quoted" or task["run"]:
                abort(409, description="任务当前不能确认制作。")

        with db() as c:
            task = owner(c, "agent_task", tid, t)
            validate(task)
            if task["run"]:
                return jsonify(task_view(c, services, task))
            locked = json.loads(task["locked"]) if task["locked"] else None

        def bind(c, rid):
            cur = owner(c, "agent_task", tid, t)
            validate(cur)
            limit = int(os.getenv("TRUPIC_AGENT_ACTIVE_LIMIT", "0"))
            if (
                limit
                and sum(
                    run_status(c, row) in ("queued", "running", "reviewing")
                    for row in c.execute(
                        "SELECT * FROM agent_task WHERE tenant=? AND run IS NOT NULL",
                        (t,),
                    )
                )
                >= limit
            ):
                abort(429, description="正在制作的任务已达上限，请稍后确认。")
            c.execute(
                "UPDATE agent_task SET run=?,status='queued',approval_key=? WHERE id=?",
                (rid, key, tid),
            )
            event(c, cur, "reserved", {"run": rid, "cost": cur["cost"]})

        submit = dict(
            requestKey="agent:" + tid, quote=task["quote"], confirmedCost=task["cost"]
        )
        values = json.loads(task["input"])
        if ref := values.get("workRef"):

            def bind_revision(c, job, spec):
                rid = ident()
                bind(c, rid)
                spec["plan"]["agentTask"] = tid
                spec["plan"]["creationRun"] = rid
                c.execute(
                    "INSERT INTO creative_run VALUES(?,?,?,?,?,?,?,?)",
                    (
                        rid,
                        t,
                        submit["requestKey"],
                        "作品修改",
                        values["brief"],
                        dump({"cost": task["cost"]}),
                        dump(
                            [{"job": job, "role": "revision", "label": "修改后的作品"}]
                        ),
                        now(),
                    ),
                )

            services["enqueue"](
                t,
                {**submit, "confirmed": True, "option": v.get("option", 0)},
                ref["id"],
                agent_reserve=bind_revision,
            )
        else:
            services["creation_submit"](
                t, submit, locked_copy=locked, on_reserve=bind, agent_task=tid
            )
        with db() as c:
            current = owner(c, "agent_task", tid, t)
            validate(current)
            return jsonify(task_view(c, services, current))

    @app.post("/api/agent/tasks/<tid>/cancel")
    def agent_cancel(tid):
        t, v = tenant(), body()
        with db(True) as c:
            task = owner(c, "agent_task", tid, t)
            check_revision(task, v.get("revision"))
            if task["run"] and task["status"] != "cancelled":
                run = owner(c, "creative_run", task["run"], t)
                jobs = [owner(c, "job", i["job"], t) for i in json.loads(run["items"])]
                if any(j["state"] != "queued" for j in jobs):
                    abort(
                        409,
                        description="任务已经开始制作，当前无法撤销。请查看真实进度。",
                    )
                for j in jobs:
                    c.execute(
                        "UPDATE job SET state='cancelled',stage=NULL WHERE id=?",
                        (j["id"],),
                    )
                    wallet.finish(c, t, j["id"], False)
            if task["status"] != "cancelled":
                c.execute("UPDATE agent_task SET status='cancelled' WHERE id=?", (tid,))
                event(c, task, "cancelled", {})
            return jsonify(task_view(c, services, owner(c, "agent_task", tid, t)))

    @app.get("/api/agent/tasks/<tid>/events")
    def agent_events(tid):
        t = tenant()
        after = request.args.get("after", 0, type=int)
        with db() as c:
            task = owner(c, "agent_task", tid, t)
            return jsonify(
                events=[
                    dict(
                        eventId=r["seq"],
                        seq=r["seq"],
                        task=tid,
                        revision=r["revision"],
                        type=r["type"],
                        timestamp=r["created"],
                        payload=json.loads(r["payload"]),
                    )
                    for r in c.execute(
                        "SELECT * FROM agent_event WHERE task=? AND seq>? ORDER BY seq LIMIT 200",
                        (tid, after),
                    )
                ],
                task=task_view(c, services, task),
            )
