"""Audition an approved ending and bind the selected recording to its production quote."""
import json
import time

from flask import abort, jsonify, send_file
from itsdangerous import BadSignature

from .agent_store import check_revision, event
from .merchant_voice_revision import preview_ending
from .store import DATA, db, dump, ident

STYLES = {"warm": "温和介绍", "bright": "轻快招呼"}


def register(app, services, task_view):
    owner, tenant, body = (services[k] for k in ("owner", "reqtenant", "body"))
    signer = services["quotes"]

    def checked_task(c, tid, t, revision):
        row = owner(c, "agent_task", tid, t)
        check_revision(row, revision)
        brief = json.loads(row["brief"])
        shots = brief.get("storyboard") or []
        if (row["status"] != "quoted" or row["run"] or not row["locked"] or
                not brief.get("productNarration") or not shots or not shots[-1].get("narration")):
            abort(409, description="请先确认有片尾口播的逐镜脚本。")
        return row, brief

    def signed_quote(row):
        is_edit = bool(json.loads(row["input"]).get("workRef"))
        options = {"salt": "revision"} if is_edit else {}
        try:
            return signer.loads(row["quote"], max_age=1800, **options), options
        except BadSignature:
            abort(409, description="报价已过期，请刷新报价后重新选择片尾。")

    @app.post("/api/agent/tasks/<tid>/ending-previews")
    def ending_previews(tid):
        t, revision = tenant(), body().get("revision")
        with db(True) as c:
            row, brief = checked_task(c, tid, t, revision)
            signed_quote(row)
            if takes := brief.get("endingTakes"):
                return jsonify(takes=takes)
            lease = c.execute("SELECT revision,expires FROM agent_option_lease WHERE task=?", (tid,)).fetchone()
            if lease and lease["revision"] == revision and lease["expires"] > time.time():
                abort(409, description="正在生成这两种片尾读法，请稍候。")
            token, batch = ident(), row["quote_id"]
            c.execute("INSERT OR REPLACE INTO agent_option_lease VALUES(?,?,?,?)", (tid, revision, token, time.time() + 600))
        cache = DATA / t / "ending-previews" / tid / batch
        try:
            takes = []
            for style, label in STYLES.items():
                result = preview_ending(cache, brief["storyboard"], style)
                takes.append(dict(style=style, label=label, text=result["text"], key=result["takeKey"],
                                  seconds=round(result["seconds"], 3),
                                  readback=result.get("readback"),
                                  url=f"/api/agent/tasks/{tid}/ending-previews/{batch}/{style}"))
            with db(True) as c:
                _, current = checked_task(c, tid, t, revision)
                current.update(endingTakes=takes, endingBatch=batch)
                c.execute("UPDATE agent_task SET brief=? WHERE id=?", (dump(current), tid))
            return jsonify(takes=takes)
        finally:
            with db(True) as c:
                c.execute("DELETE FROM agent_option_lease WHERE task=? AND token=?", (tid, token))

    @app.get("/api/agent/tasks/<tid>/ending-previews/<batch>/<style>")
    def ending_audio(tid, batch, style):
        t = tenant()
        with db() as c:
            row = owner(c, "agent_task", tid, t)
            brief = json.loads(row["brief"])
            take = next((r for r in brief.get("endingTakes", []) if r["style"] == style), None)
            if not take or brief.get("endingBatch") != batch:
                abort(404)
        path = DATA / t / "ending-previews" / tid / batch / take["key"] / "voice.wav"
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="audio/wav", conditional=True)

    @app.post("/api/agent/tasks/<tid>/ending-choice")
    def ending_choice(tid):
        t, v = tenant(), body()
        with db(True) as c:
            row, brief = checked_task(c, tid, t, v.get("revision"))
            q, options = signed_quote(row)
            take = next((r for r in brief.get("endingTakes", []) if r["style"] == v.get("style")), None)
            if not take:
                raise ValueError("请先生成两种片尾试听，再选择读法。")
            if brief.get("selectedEnding") != take["style"]:
                selection = {"task": tid, "batch": brief["endingBatch"], "key": take["key"]}
                if options:
                    q["endingTake"] = selection
                else:
                    for entry in q["items"]:
                        if entry["spec"]["kind"] == "video":
                            entry["spec"]["endingTake"] = selection
                brief["selectedEnding"] = take["style"]
                c.execute("UPDATE agent_task SET brief=?,quote=?,quote_id=?,revision=revision+1 WHERE id=?",
                          (dump(brief), signer.dumps(q, **options), ident(), tid))
                row = owner(c, "agent_task", tid, t)
                event(c, row, "quoted", {"endingStyle": take["style"], "cost": row["cost"]})
            return jsonify(task_view(c, services, row))
