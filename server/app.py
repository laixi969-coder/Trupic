import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask,
    abort,
    jsonify,
    request,
    send_file,
    send_from_directory,
    session,
)
from itsdangerous import BadSignature, URLSafeTimedSerializer
from PIL import Image, ImageDraw
from io import BytesIO
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from . import model, providers
from .background import make_scene
from .creative import (
    CASES,
    METHODS,
    NUMCLAIM,
    RISK,
    draft_copy,
    generate_copy,
    next_suggestion,
    prepare,
)
from .governance import active_rule, discover, run_tests, retrieve_method
from .media import ROOT, SIZES, inspect_upload, render
from .store import DATA, audit, db, dump, ident, init, now, secret, tenant_new
from . import event_sources, costs
from .topics import weekly, check_topic
from .formats import output_spec
from .design import (
    STYLES,
    choose_style,
    next_style,
    industry_examples,
    layout_alternative,
)
from .typography import Typesetter, inspect_face
from .lettering import OPTIONS as LETTERING_OPTIONS
from .campaign import storyboard
from .shot_detail import merchant_detail
from .prompt_agent import full_poster_prompt, optimize
from .product_bundle import register as register_bundles
from .auto_creation import register as register_creations
from .auto_pipeline import shared_copy
from .model_tools import register as register_model_tools
from .skill_library import attach as attach_skills, catalog as skill_library_catalog, effective_versions, manage_version
from .visual_review import (
    FIDELITY,
    LayoutOverflow,
    inspect_export,
    validate_region,
    content_review,
    image_message,
    preflight,
)

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=secret("session.key"),
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,
    SESSION_COOKIE_NAME="trupic_workspace",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=dt.timedelta(days=180),
)
quotes = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="trupic-creative-quote")
COST = {"copy": 0, "poster": 4, "video": 12}
LABEL = {"copy": "推广文案", "poster": "营销海报", "video": "宣传短片"}
ADMIN = os.getenv("TRUPIC_ADMIN_KEY") or secret("admin.key")
init()
with db(True) as c:
    c.execute("CREATE TABLE IF NOT EXISTS admin_auth (id INTEGER PRIMARY KEY CHECK(id=1), password_hash TEXT NOT NULL)")
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="trupic")


def body():
    return request.get_json(silent=True) or {}


def string(val, limit=500):
    return val.strip()[:limit] if isinstance(val, str) else ""


def reqtenant():
    if not session.get("tenant"):
        t = ident()
        with db(True) as c:
            tenant_new(c, t)
        session["tenant"] = t
        session.permanent = True
    return session["tenant"]


def admin_credential(c):
    # Deployment configuration deliberately takes precedence over UI settings.
    if os.getenv("TRUPIC_ADMIN_KEY"):
        return os.environ["TRUPIC_ADMIN_KEY"], False
    row = c.execute("SELECT password_hash FROM admin_auth WHERE id=1").fetchone()
    return (row[0], True) if row else (ADMIN, False)


def admin_token(credential):
    return hmac.new(app.config["SECRET_KEY"].encode(), credential.encode(), hashlib.sha256).hexdigest()


def admin_matches(password, credential, hashed):
    return check_password_hash(credential, password) if hashed else hmac.compare_digest(password.encode(), credential.encode())


def is_admin(c):
    token = session.get("admin")
    return isinstance(token, str) and hmac.compare_digest(token, admin_token(admin_credential(c)[0]))


def require_admin():
    with db() as c:
        if not is_admin(c):
            abort(403, description="请使用当前管理密码重新登录。")


def owner(c, table, id, t):
    row = c.execute(
        f"SELECT * FROM {table} WHERE id=? AND tenant=?", (id, t)
    ).fetchone()
    if not row:
        abort(404, description="找不到这项内容。")
    return row


@app.before_request
def protect():
    if request.path == "/api/fonts":
        request.max_content_length = 34 * 1024 * 1024
    origin = request.headers.get("Origin")
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and origin
        and urlparse(origin).hostname != request.host.split(":")[0]
    ):
        abort(403, description="请从当前工作室提交操作。")


@app.after_request
def headers(resp):
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.errorhandler(ValueError)
def invalid(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(HTTPException)
def error(e):
    return jsonify(
        error=(
            "单款字体最大为 32 MB。"
            if request.path == "/api/fonts"
            else "请上传小于 12 MB 的图片。"
        )
        if e.code == 413
        else e.description
    ), e.code


def asset_json(row):
    a = dict(row)
    inf = json.loads(a["info"])
    return dict(
        id=a["id"],
        name=a["name"],
        created=a["created"],
        url="/api/assets/" + a["id"] + "/image",
        original="/api/assets/" + a["id"] + "/original",
        **inf,
    )


def history(c, t):
    res = []
    for row in c.execute(
        """SELECT v.spec,v.copy, json_extract(tr.item,'$.tag') AS topic_tag,
                  (EXISTS(SELECT 1 FROM downloads d WHERE d.work=w.id AND d.count>0)
                   OR EXISTS(SELECT 1 FROM version edited WHERE edited.work=w.id AND edited.n>1)) AS engaged
           FROM work w JOIN version v ON v.work=w.id AND w.current=v.n
           LEFT JOIN topic_record tr ON tr.tenant=w.tenant AND tr.id=json_extract(v.spec,'$.plan.topic.id')
           WHERE w.tenant=? ORDER BY w.created DESC,w.rowid DESC LIMIT 35""",
        (t,),
    ):
        p = json.loads(row["spec"])["plan"]
        cp = json.loads(row["copy"])
        res.append(
            dict(
                title=cp["title"],
                method=p["method"],
                original=p["original"],
                preferredTag=row["topic_tag"] if row["engaged"] else None,
            )
        )
    return res


def pack(c, w, all_versions=False):
    versions = []
    query = (
        "SELECT * FROM version WHERE work=?"
        + ("" if all_versions else " AND n=?")
        + " ORDER BY n DESC"
    )
    for r in c.execute(query, (w["id"],) if all_versions else (w["id"], w["current"])):
        spec = json.loads(r["spec"])
        copy = json.loads(r["copy"])
        n = r["n"]
        base = f"/api/works/{w['id']}/v/{n}"
        folder = DATA / w["tenant"] / "works" / w["id"] / str(n)
        suggestion = next_suggestion(spec, copy)[1] if all_versions else {}
        versions.append(
            dict(
                n=n,
                created=r["created"],
                suggestion=suggestion,
                layoutSuggestion=layout_alternative(spec["plan"], copy)
                if all_versions and w["kind"] != "copy"
                else None,
                **copy,
                brief=spec["plan"]["original"],
                plan=spec["plan"],
                quality=json.loads(r["quality"]),
                asset=spec["asset"],
                ratio=spec["ratio"],
                poster=base + "/poster",
                download=base + "/download",
                designSource=base + "/design-source"
                if w["kind"] == "poster"
                and (folder / "poster.svg").is_file()
                else None,
                editSource=base + "/edit-source"
                if w["kind"] == "video" and (folder / "edit.zip").is_file()
                else None,
                openDesignSource=base + "/open-design-source"
                if w["kind"] == "video" and (folder / "open-design.zip").is_file()
                else None,
                video=base + "/video" if w["kind"] == "video" else None,
            )
        )
    current = next(v for v in versions if v["n"] == w["current"])
    return dict(
        id=w["id"],
        kind=w["kind"],
        created=w["created"],
        current=w["current"],
        title=current["title"] or current["body"],
        cover=current["poster"],
        **({"versions": versions} if all_versions else {}),
    )


@app.get("/api/state")
def state():
    t = reqtenant()
    with db() as c:
        m = c.execute("SELECT * FROM merchant WHERE id=?", (t,)).fetchone()
        prof = json.loads(m["profile"])
        works = [
            pack(c, w)
            for w in c.execute(
                "SELECT * FROM work WHERE tenant=? ORDER BY created DESC,rowid DESC",
                (t,),
            )
        ]
        assets = [
            asset_json(r)
            for r in c.execute(
                "SELECT * FROM asset WHERE tenant=? ORDER BY created DESC,rowid DESC",
                (t,),
            )
        ]
        ledger = [
            dict(x)
            for x in c.execute(
                "SELECT delta,note,created FROM ledger WHERE tenant=? ORDER BY id DESC LIMIT 80",
                (t,),
            )
        ]
        jobs = [
            dict(x)
            for x in c.execute(
                "SELECT id,state,work,error,created,json_extract(spec,'$.plan.autoCreation') AS autoCreation FROM job WHERE tenant=? AND state IN ('queued','running','failed') ORDER BY created DESC,rowid DESC LIMIT 15",
                (t,),
            )
        ]
        recs = weekly(c, t, prof, history(c, t))
        return jsonify(
            profile=prof,
            posterStyles=[{"id": key, **value} for key, value in STYLES.items()],
            posterExamples=industry_examples(),
            fonts=[
                {"id": r["id"], **json.loads(r["info"])}
                for r in c.execute(
                    "SELECT id,info FROM brand_font WHERE tenant=? ORDER BY created DESC,rowid DESC",
                    (t,),
                )
            ],
            login=m["login"],
            admin=is_admin(c),
            credits=m["credits"],
            works=works,
            assets=assets,
            cases=CASES,
            recs=recs,
            ledger=ledger,
            jobs=jobs,
            prices=COST,
        )


@app.get("/api/topics")
def get_topics():
    t = reqtenant()
    with db() as c:
        profile = json.loads(
            c.execute("SELECT profile FROM merchant WHERE id=?", (t,)).fetchone()[0]
        )
        return jsonify(weekly(c, t, profile, history(c, t)))


@app.post("/api/profile")
def profile():
    t = reqtenant()
    v = body()
    p = {
        k: string(v.get(k), 400 if k == "facts" else 80)
        for k in ("name", "industry", "product", "audience", "facts", "tone", "city")
    }
    if not p["name"]:
        raise ValueError("请填写商家名称。")
    with db(True) as c:
        previous = json.loads(
            c.execute("SELECT profile FROM merchant WHERE id=?", (t,)).fetchone()[0]
        )
        font_id = string(v.get("brandFont", previous.get("brandFont", "")), 64)
        if font_id:
            owner(c, "brand_font", font_id, t)
        p["brandFont"] = font_id
        c.execute("UPDATE merchant SET profile=? WHERE id=?", (dump(p), t))
    return jsonify(ok=True)


@app.post("/api/fonts")
def upload_font():
    tenant = reqtenant()
    upload = request.files.get("font")
    if not upload:
        raise ValueError("请选择 TTF 或 OTF 文件。")
    data = upload.stream.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024:
        raise ValueError("单款字体最大为 32 MB。")
    info = inspect_face(data)
    digest = hashlib.sha256(data).hexdigest()
    with db(True) as c:
        old = c.execute(
            "SELECT id,info FROM brand_font WHERE tenant=? AND digest=?",
            (tenant, digest),
        ).fetchone()
        if old:
            return jsonify(id=old["id"], **json.loads(old["info"]))
        font_id = ident()
        folder = DATA / tenant / "fonts"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / font_id).write_bytes(data)
        c.execute(
            "INSERT INTO brand_font VALUES(?,?,?,?,?)",
            (font_id, tenant, digest, dump(info), now()),
        )
    return jsonify(id=font_id, **info)


@app.get("/api/fonts/<font_id>/sample.png")
def font_sample(font_id):
    tenant = reqtenant()
    with db() as c:
        owner(c, "brand_font", font_id, tenant)
    sample = Image.new("RGB", (760, 104), "#f5f4ec")
    ts = Typesetter(DATA / tenant / "fonts" / font_id)
    ts.draw(
        ImageDraw.Draw(sample),
        "春山入盏   Tea 28.50元",
        (18, 8, 742, 96),
        55,
        "display",
        "#213d30",
    )
    buffer = BytesIO()
    sample.save(buffer, "PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png")


@app.post("/api/account/<action>")
def account(action):
    t = reqtenant()
    v = body()
    login = string(v.get("login"), 64).lower()
    pw = string(v.get("password"), 160)
    if action == "logout":
        session.clear()
        return jsonify(ok=True)
    if action == "admin":
        with db(True) as c:
            credential, hashed = admin_credential(c)
            if not admin_matches(pw, credential, hashed):
                abort(403, description="管理密码不正确；首次登录请使用本机初始管理密钥，它与商家账号密码不同。")
            session["admin"] = admin_token(credential)
            audit(c, t, "管理登录", "")
        return jsonify(ok=True)
    if not login or len(pw) < 8:
        raise ValueError("请填写账号，并使用至少 8 位的密码。")
    with db(True) as c:
        if action == "register":
            if c.execute("SELECT id FROM merchant WHERE login=?", (login,)).fetchone():
                raise ValueError("账号已被使用，请登录或换一个名称。")
            if c.execute("SELECT login FROM merchant WHERE id=?", (t,)).fetchone()[0]:
                raise ValueError("当前工作空间已绑定账号。")
            c.execute(
                "UPDATE merchant SET login=?,password=? WHERE id=?",
                (login, generate_password_hash(pw), t),
            )
        elif action == "login":
            r = c.execute("SELECT * FROM merchant WHERE login=?", (login,)).fetchone()
            if not r or not check_password_hash(r["password"], pw):
                abort(401, description="账号或密码不正确。")
            session.clear()
            session["tenant"] = r["id"]
            session.permanent = True
        else:
            abort(404)
    return jsonify(ok=True)


@app.post("/api/assets")
def upload():
    t = reqtenant()
    f = request.files.get("image")
    if not f:
        raise ValueError("请选择素材图片。")
    id = ident()
    folder = DATA / t / "assets" / id
    try:
        info = inspect_upload(f.stream, folder)
        with db(True) as c:
            c.execute(
                "INSERT INTO asset VALUES(?,?,?,?,?)",
                (
                    id,
                    t,
                    string(Path(f.filename or "素材").name, 100),
                    dump(info),
                    now(),
                ),
            )
            return jsonify(
                asset_json(
                    c.execute("SELECT * FROM asset WHERE id=?", (id,)).fetchone()
                )
            )
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


@app.get("/api/assets/<id>/<mode>")
def asset_file(id, mode):
    with db() as c:
        r = owner(c, "asset", id, reqtenant())
    name = "original.png" if mode == "original" else json.loads(r["info"])["file"]
    return send_file(DATA / r["tenant"] / "assets" / id / name)


@app.delete("/api/assets/<id>")
def delete_asset(id):
    t = reqtenant()
    with db(True) as c:
        owner(c, "asset", id, t)
        if c.execute(
            "SELECT 1 FROM job WHERE tenant=? AND json_extract(spec,'$.asset')=? LIMIT 1",
            (t, id),
        ).fetchone():
            raise ValueError("已有任务引用此素材，需保留以供版本回看。")
        c.execute("DELETE FROM asset WHERE id=?", (id,))
    shutil.rmtree(DATA / t / "assets" / id, ignore_errors=True)
    return jsonify(ok=True)


def plan_spec(c, t, v):
    brief = string(v.get("brief"), 1200)
    kind = string(v.get("kind"))
    ratio = string(v.get("ratio") or ("story" if kind == "video" else "portrait"))
    if len(brief) < 2 or kind not in COST or ratio not in SIZES:
        raise ValueError("请填写创作需求，并选择有效的作品类型和画幅。")
    output = output_spec(kind, ratio, v.get("resolution"), v.get("dpi"))
    asset = string(v.get("asset"), 60)
    policy = string(v.get("assetMode"), 16)
    if asset:
        a = owner(c, "asset", asset, t)
        if json.loads(a["info"])["risk"] and kind != "copy":
            raise ValueError("这张图片无法可靠还原商品，请更换清晰原图。")
        if (
            kind != "copy"
            and json.loads(a["info"])["action"] == "主体抠图"
            and not v.get("assetConfirmed")
        ):
            raise ValueError("请先核对并确认商品主体及标识清晰完整。")
    region = v.get("identityRegion") if kind != "copy" else None
    if kind != "copy" and FIDELITY.search(brief):
        if not asset:
            raise ValueError(
                "这项需求需要还原实际商品，请先添加能看清包装与标识的原图。"
            )
        if not region or v.get("assetConfirmed") is not True:
            raise ValueError("请核对原图并标出要保真的商品标识或包装文字。")
    if region is not None:
        if not asset:
            raise ValueError("请先选择商品原图。")
        if v.get("assetConfirmed") is not True:
            raise ValueError("请核对原图并确认标识清晰完整。")
        validate_region(DATA / t / "assets" / asset / "original.png", region)
    prof = json.loads(
        c.execute("SELECT profile FROM merchant WHERE id=?", (t,)).fetchone()[0]
    )
    if not any(
        [prof.get("product"), prof.get("industry"), len(brief) > 6]
    ) and brief in (
        "做个海报",
        "做宣传",
        "帮我宣传",
        "写文案",
        "做海报",
        "做视频",
        "做张海报",
    ):
        raise ValueError("想宣传什么商品或门店？请补充一句，或先填写商家档案。")
    rule = active_rule(c, t)
    retrieved = retrieve_method(c, brief, prof)
    if retrieved:
        rule = {**rule, "method": retrieved["method"]}
    plan = prepare(
        brief,
        prof,
        history(c, t),
        rule,
        string(v.get("reference")),
        string(v.get("facts"), 250),
    )
    ref = c.execute(
        "SELECT c.id,c.title,c.lesson,c.kind,c.source,c.license FROM cases c JOIN rules r ON c.id=r.case_id WHERE r.id=? AND c.status='approved' AND c.category!='反面案例'",
        (plan["ruleId"],),
    ).fetchone()
    plan["output"] = output
    plan["kind"] = kind
    if kind == "video" and v.get("visualDetail") is not None:
        plan["markedDetail"] = merchant_detail(v, DATA / t / "assets" / asset / "original.png" if asset else None)
    if kind in ("poster", "video"):
        plan["visualSource"] = (
            "concept" if not asset else
            "cutout" if policy != "original" and json.loads(a["info"])["file"] == "subject.png"
            else "photograph"
        )
        plan["lettering"] = string(v.get("lettering") or "auto")
        if plan["lettering"] not in LETTERING_OPTIONS:
            raise ValueError("请选择支持的图形文字组合。")
        plan["design"] = choose_style(plan, string(v.get("posterStyle") or "auto"))
        if plan["design"]["id"] == "ipscene" and not asset:
            raise ValueError("请先上传品牌角色参考图，才能保留角色的轮廓、配件和颜色。")
        font_id = string(v.get("fontId") or "profile", 64)
        if font_id == "profile":
            font_id = prof.get("brandFont", "")
        if font_id and font_id != "builtin":
            row = owner(c, "brand_font", font_id, t)
            plan["brandType"] = {"id": font_id, "name": json.loads(row["info"])["name"]}
    if ref:
        plan["learnedMethod"] = {
            "case": ref["title"],
            **{k: ref[k] for k in ("id", "lesson", "kind", "source", "license")},
        }
    if retrieved:
        plan["retrievedMethod"] = retrieved
    source = string(v.get("source") or "一句话创作", 100)
    if topic_id := string(v.get("topicId"), 64):
        record = c.execute(
            "SELECT item FROM topic_record WHERE tenant=? AND id=?", (t, topic_id)
        ).fetchone()
        if not record:
            raise ValueError("此主题已不可用，请重新选题。")
        item = json.loads(record["item"])
        check_topic(c, t, item)
        plan["topic"] = {
            k: item[k] for k in ("title", "week", "basis", "source", "relevance", "recentUses", "eventId", "starts", "ends") if k in item
        }
        plan["topic"]["id"] = topic_id
        source = item["id"]
    attach_skills(plan, kind, overrides=effective_versions(c, t))
    return dict(
        plan=plan,
        kind=kind,
        ratio=ratio,
        asset=asset,
        assetMode=policy,
        identityRegion=region,
        variant=0,
        source=source,
    )


@app.post("/api/preview")
def preview():
    t = reqtenant()
    with db() as c:
        s = plan_spec(c, t, body())
    preflight(s, DATA / t / "assets")
    optimize(s)
    return jsonify(
        plan=s["plan"],
        fullPosterPrompt=full_poster_prompt(s["plan"], draft_copy(s["plan"])) if s["kind"] == "poster" else None,
        cost=COST[s["kind"]],
        kind=s["kind"],
        ratio=s["ratio"],
        engine=model.engine_name(),
        quote=quotes.dumps({"tenant": t, "spec": s, "cost": COST[s["kind"]]}),
    )


def enough(c, t, cost):
    balance = c.execute("SELECT credits FROM merchant WHERE id=?", (t,)).fetchone()[0]
    pending = c.execute(
        "SELECT COALESCE(SUM(cost),0) FROM job WHERE tenant=? AND state IN ('queued','running')",
        (t,),
    ).fetchone()[0]
    if balance - pending < cost:
        raise ValueError("可用体验积分不足，可选择免费文案创作。")


def enqueue(t, v, work=None):
    key = string(v.get("requestKey"), 90)
    if not key:
        raise ValueError("缺少请求标识，请刷新后再试。")
    with db(True) as c:
        old = c.execute(
            "SELECT id,work,state FROM job WHERE tenant=? AND request_key=?", (t, key)
        ).fetchone()
        if old:
            return dict(old)
        if work:
            w = owner(c, "work", work, t)
            if c.execute(
                "SELECT 1 FROM job WHERE work=? AND state IN ('queued','running')",
                (work,),
            ).fetchone():
                raise ValueError("此作品仍在生成新版本，请稍后再试。")
            r = c.execute(
                "SELECT * FROM version WHERE work=? AND n=?",
                (work, int(v.get("base") or w["current"])),
            ).fetchone()
            if not r:
                abort(404)
            s = json.loads(r["spec"])
            nxt = c.execute(
                "SELECT MAX(n)+1 FROM version WHERE work=?", (work,)
            ).fetchone()[0]
            s["variant"] = nxt - 1
            cost = 0
            current_copy = json.loads(r["copy"])
            action = v.get("action", "revision")
            if action == "layout":
                if s["kind"] == "copy":
                    raise ValueError("纯文案作品无需调整画面版式。")
                s["plan"]["design"] = layout_alternative(s["plan"], current_copy)
                s["plan"]["layoutOverride"] = True
                s["replacement"] = current_copy
            else:
                s["plan"], suggestion = next_suggestion(s, current_copy)
                if action == "redesign":
                    s.pop("replacement", None)
                    design = s["plan"].get("design")
                    if design and design["selection"] == "auto":
                        s["plan"]["design"] = next_style(design)
                elif action == "revision":
                    s["replacement"] = suggestion
                else:
                    raise ValueError("请选择有效的修改方式。")
            optimize(s, infer=False, previous=s["plan"].get("promptBrief"))
        else:
            if v.get("quote"):
                try:
                    q = quotes.loads(v["quote"], max_age=1800)
                except BadSignature:
                    raise ValueError("这份方案已过期，请返回重新分析。")
                if q["tenant"] != t:
                    abort(403)
                s = q["spec"]
                check_topic(c, t, s["plan"].get("topic"))
                if s["asset"]:
                    owner(c, "asset", s["asset"], t)
            else:
                s = plan_spec(c, t, v)
            cost = COST[s["kind"]]
            work = ident()
            nxt = 1
            if cost and (v.get("confirmedCost") != cost or not v.get("confirmed")):
                raise ValueError("请确认本次积分用量后再制作。")
        enough(c, t, cost)
        id = ident()
        c.execute(
            "INSERT INTO job(id,tenant,request_key,spec,state,cost,work,version,error,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (id, t, key, dump(s), "queued", cost, work, nxt, None, now()),
        )
    pool.submit(produce, id)
    return dict(id=id, state="queued", work=work)


@app.post("/api/jobs")
def create_job():
    return jsonify(enqueue(reqtenant(), body()))


@app.post("/api/works/<id>/revise")
def revise(id):
    return jsonify(enqueue(reqtenant(), body(), id))


def produce(id):
    with db(True) as c:
        j = c.execute(
            "SELECT * FROM job WHERE id=? AND state='queued'", (id,)
        ).fetchone()
        if not j:
            return
        c.execute(
            "UPDATE job SET state='running',worker_pid=? WHERE id=?", (os.getpid(), id)
        )
    t, work, n = j["tenant"], j["work"], j["version"]
    s = json.loads(j["spec"])
    p = s["plan"]
    p.setdefault("kind", s["kind"])
    dest = DATA / t / "works" / work / str(n)
    try:
        if (p.get("autoCreation") and model.route("vision")["model"]) or (not p.get("bundleRole") and not p.get("autoCreation")):
            preflight(s, DATA / t / "assets")
        if not p.get("promptBrief"):
            optimize(s)
            with db(True) as c:
                c.execute("UPDATE job SET spec=? WHERE id=?", (dump(s), id))
        cached_copy = j["copy_checkpoint"]
        cp = (
            json.loads(cached_copy)
            if cached_copy
            else shared_copy(s) if p.get("autoCreation") and n == 1 else s.get("replacement") or generate_copy(p, 0)
        )
        ap = None
        if s["asset"]:
            with db() as c:
                a = owner(c, "asset", s["asset"], t)
            filename = "original.png" if s.get("assetMode") == "original" else json.loads(a["info"])["file"]
            ap = DATA / t / "assets" / s["asset"] / filename
        if s["kind"] == "video":
            cp["storyboard"] = storyboard(p, cp, ap)
        if s["kind"] == "poster" and p.get("posterArt") and p.get("output"):
            cp["fullPosterPrompt"] = full_poster_prompt(p, cp)
        known = (
            p["original"]
            + " "
            + p["facts"]
            + " "
            + json.dumps(p["profile"], ensure_ascii=False)
        )
        words = cp["title"] + " " + cp["body"] + " " + cp["cta"]
        if s["kind"] == "video" and cp["storyboard"][1].get("evidence"):
            words += " " + cp["storyboard"][1]["line"]
            known += " " + p.get("markedDetail", {}).get("label", "")
        if RISK.search(words) or any(
            claim not in known for claim in NUMCLAIM.findall(words)
        ):
            raise ValueError("检测到未经确认的经营声明，请补充事实后重新创作。")
        if not cached_copy:
            with db(True) as c:
                c.execute("UPDATE job SET copy_checkpoint=? WHERE id=?", (dump(cp), id))
        if p.get("autoCreation") and s["kind"] != "copy" and p.get("bundleRole") not in ("white","overlay","box","bag","card"):
            background, visual_engine = None, "本地商品素材排版"
            if s["kind"] == "video" and model.route("video")["model"]:
                from .video_api import prepare_background
                p["videoBackground"] = str(prepare_background(dest, p, cp))
                visual_engine = model.route("video")["model"]
            else:
                background, visual_engine = make_scene(dest, p, ap, s["kind"], n == 1, strict=True)
        elif p.get("bundleRole") or p.get("autoCreation"):
            background, visual_engine = None, "本地商品素材排版"
        else:
            background, visual_engine = make_scene(dest, p, ap, s["kind"], n == 1)
        cp["visualEngine"] = visual_engine
        custom_font = None
        if p.get("brandType"):
            with db() as c:
                record = owner(c, "brand_font", p["brandType"]["id"], t)
            custom_font = DATA / t / "fonts" / record["id"]
        output = p.get("output") or output_spec(s["kind"], s["ratio"])
        visual = None
        if s["kind"] == "copy":
            layout = render(
                dest,
                p,
                cp,
                s["kind"],
                ap,
                s["ratio"],
                s["variant"],
                background,
                custom_font,
            )
        else:
            original = ap.with_name("original.png") if ap else None
            if p.get("bundleRole") == "overlay":
                original = None
            previous = json.loads(j["visual_review"] or "{}")
            visual = {"status": "checking", "attempts": previous.get("attempts", [])}
            for repair in (False, True):
                chosen = ap
                if repair and ap and p.get("bundleRole") != "overlay":
                    last_issues = visual["attempts"][-1]["issues"]
                    intact_mask = ap.name == "subject.png" and not any(
                        "抠图" in issue or "蒙版" in issue for issue in last_issues
                    )
                    chosen = ap if intact_mask else original
                visual.pop("content", None)
                try:
                    layout = render(
                        dest,
                        p,
                        cp,
                        s["kind"],
                        chosen,
                        s["ratio"],
                        s["variant"],
                        background,
                        custom_font,
                        repair=repair,
                    )
                    try:
                        issues = inspect_export(
                            dest,
                            layout,
                            original,
                            chosen,
                            s.get("identityRegion"),
                            cp,
                            output,
                        )
                    except (OSError, ValueError, subprocess.SubprocessError) as exc:
                        issues = ["导出文件读取失败：" + str(exc)[:100]]
                    try:
                        review = (
                            None if p.get("bundleRole") and not p.get("autoCreation")
                            else content_review(dest, original, s, cp, layout)
                        )
                    except (
                        OSError,
                        ValueError,
                        KeyError,
                        IndexError,
                        TypeError,
                        subprocess.SubprocessError,
                    ):
                        # A damaged first export can also prevent preparing the model input.
                        review = (
                            None
                            if issues and not repair
                            else {
                                "status": "unavailable",
                                "reason": "已配置的视觉模型未返回有效结果，请重试。",
                            }
                        )
                    if review:
                        visual["content"] = review
                        if review["status"] != "pass":
                            issues.append(review["reason"])
                except LayoutOverflow as exc:
                    issues = [str(exc)]
                terminal = visual.get("content", {}).get("status") in (
                    "source",
                    "unavailable",
                )
                visual["attempts"].append(
                    {
                        "repair": repair,
                        "issues": issues,
                        "content": visual.get("content"),
                    }
                )
                visual["status"] = (
                    ("blocked" if repair or terminal else "repairing")
                    if issues
                    else ("repaired" if repair else "passed")
                )
                with db(True) as c:
                    c.execute(
                        "UPDATE job SET visual_review=? WHERE id=?", (dump(visual), id)
                    )
                if not issues:
                    break
                if terminal:
                    raise ValueError(visual["content"]["reason"])
                if repair:
                    raise ValueError(
                        "成品复检未通过："
                        + "；".join(i.rstrip("。") for i in issues[:3])
                        + "。请更换近景原图或调整文案后重新创作。"
                    )
        files = ["poster.png", "copy.txt"] + (
            ["video.mp4"] if s["kind"] == "video" else []
        )
        if any(
            not (dest / f).is_file() or not (dest / f).stat().st_size for f in files
        ):
            raise ValueError("文件生成失败，请重试。")
        dims = (output["width"], output["height"])
        with Image.open(dest / "poster.png") as img:
            if img.size != dims:
                raise ValueError("输出规格异常，请重新制作。")
            if s["kind"] == "poster" and any(
                abs(v - output["dpi"]) > 1 for v in img.info.get("dpi", (0, 0))
            ):
                raise ValueError("PNG 印刷精度与已确认设置不一致。")
            img.verify()
        checks = [
            {
                "label": "事实检查",
                "detail": cp.get("review", "已核对数字声明与绝对化承诺。"),
            },
            {
                "label": "文案与画面",
                "detail": "共同围绕「"
                + p["angle"]
                + "」。"
                + (
                    "使用商家上传的照片。"
                    if ap
                    else (
                        "内置场景图已标注为创意示意。"
                        if background or p.get("scenePhoto")
                        else "采用文字构图。"
                    )
                ),
            },
            {
                "label": "导出检查",
                "detail": "已校验 PNG 文件及 "
                + " × ".join(map(str, dims))
                + " 像素画幅及文案文件。",
            },
        ]
        if renderer := layout.get("videoRenderer"):
            checks.append({"label": "短片渲染引擎", "detail": renderer})
        if visual:
            coverage = "已检查导出 PNG" + (
                "及 MP4 全部 216 帧，抽查三个镜头首、中、尾共九帧"
                if s["kind"] == "video"
                else ""
            )
            checks.append(
                {
                    "label": "成品视觉审核",
                    "detail": coverage + "的画面、文字边界、字号与对比度。",
                }
            )
            if ap:
                checks.append(
                    {
                        "label": "商品原图比对",
                        "detail": "按成品中的商品位置逐区比对原图。"
                        + (
                            "已单独比对商家框选的标识。"
                            if s.get("identityRegion")
                            else ""
                        ),
                    }
                )
            if review := visual.get("content"):
                checks.append(
                    {
                        "label": "画面语义复核",
                        "detail": review["model"] + " · " + review["reason"],
                    }
                )
            if visual["status"] == "repaired":
                checks.append(
                    {
                        "label": "自动修复",
                        "detail": "；".join(visual["attempts"][-2]["issues"])
                        + "。已重制摄影构图和文字层"
                        + ("，商品像素来自实拍原图" if ap else "")
                        + "，复检通过。",
                    }
                )
        if art := p.get("posterArt"):
            checks.append(
                {
                    "label": "海报美术指导",
                    "detail": "、".join(art.get("methods", ["hiccai-poster"]))
                    + " · "
                    + art["mechanism"]
                    + " · "
                    + art["concept"],
                }
            )
        if reference := p.get("learnedMethod"):
            checks.append(
                {
                    "label": "引用的案例方法",
                    "detail": reference["case"] + " · " + reference["lesson"],
                }
            )
        if reference := p.get("retrievedMethod"):
            checks.append(
                {
                    "label": "跨案例检索",
                    "detail": reference["kind"]
                    + " · "
                    + reference["title"]
                    + " · 命中「"
                    + "、".join(reference["matched"])
                    + "」 · "
                    + reference["lesson"],
                }
            )
        if flag := cp.get("reviewFlag"):
            checks.append(
                {"label": "待抽查", "detail": (cp["attemptedModel"] + " · " if cp.get("attemptedModel") else "") + flag + "，已采用本地规则成稿。"}
            )
        if writing := cp.get("writingSkill"):
            checks.append(
                {
                    "label": "文案 Skill",
                    "detail": f"{writing['name']} v{writing['version']} · {writing['mode']} · "
                    + "、".join(writing["sections"]),
                }
            )
        if s["kind"] in ("poster", "video"):
            style = p.get("design") or choose_style(p)
            font_info = "、".join(layout["fonts"])
            checks.append(
                {
                    "label": "版式与用字",
                    "detail": (
                        "摄影主视觉（自动修复）"
                        if visual["status"] == "repaired"
                        else style["name"]
                    )
                    + " · 实际用字："
                    + font_info
                    + (
                        "。品牌字体未覆盖的字符已逐字搭配。"
                        if layout["fallback"]
                        else "。"
                    ),
                }
            )
        if s["kind"] == "video":
            checks.append(
                {
                    "label": "短片检查",
                    "detail": f"已核实 {dims[0]} × {dims[1]}、9 秒、24 fps 画面和声音轨道。",
                }
            )
        with db(True) as c:
            if n == 1:
                c.execute(
                    "INSERT INTO work VALUES(?,?,?,?,?)", (work, t, s["kind"], 1, now())
                )
                if topic := p.get("topic"):
                    c.execute(
                        "UPDATE topic_record SET first_work=? WHERE tenant=? AND id=? AND first_work IS NULL",
                        (work, t, topic["id"]),
                    )
                elif "-W" in s.get("source", ""):
                    # Also accept a signed preview issued before topic IDs were introduced.
                    c.execute(
                        """UPDATE topic_record SET first_work=? WHERE tenant=? AND first_work IS NULL
                           AND json_extract(item,'$.id')=? AND json_extract(item,'$.brief')=?""",
                        (work, t, s["source"], p["original"]),
                    )
            c.execute(
                "INSERT INTO version VALUES(?,?,?,?,?,?)",
                (work, n, dump(s), dump(cp), dump(checks), now()),
            )
            c.execute("UPDATE work SET current=? WHERE id=?", (n, work))
            if j["cost"]:
                c.execute(
                    "UPDATE merchant SET credits=credits-? WHERE id=?", (j["cost"], t)
                )
                c.execute(
                    "INSERT INTO ledger(tenant,job,delta,note,created)VALUES(?,?,?,?,?)",
                    (t, id, -j["cost"], LABEL[s["kind"]] + " · " + cp["title"], now()),
                )
            c.execute(
                "UPDATE job SET state='complete',error=NULL,copy_checkpoint=NULL WHERE id=?",
                (id,),
            )
    except Exception as e:
        app.logger.exception("Generation failed for %s", id)
        msg = str(e) if isinstance(e, ValueError) else "制作中断，已保留需求。请重试。"
        with db(True) as c:
            c.execute("UPDATE job SET state='failed',error=? WHERE id=?", (msg, id))


@app.get("/api/jobs/<id>")
def job_status(id):
    with db() as c:
        r = owner(c, "job", id, reqtenant())
    return jsonify({k: r[k] for k in ("id", "state", "work", "error", "version")})


@app.post("/api/jobs/<id>/retry")
def retry(id):
    t = reqtenant()
    with db(True) as c:
        j = owner(c, "job", id, t)
        if j["state"] == "failed":
            if c.execute(
                "SELECT 1 FROM version WHERE work=? AND n=?", (j["work"], j["version"])
            ).fetchone():
                raise ValueError("此版本已完成。")
            if c.execute(
                "SELECT 1 FROM job WHERE work=? AND id!=? AND state IN ('queued','running')",
                (j["work"], id),
            ).fetchone():
                raise ValueError("另一版本正在生成，请稍后再试。")
            enough(c, t, j["cost"])
            spec = json.loads(j["spec"])
            if rid := spec["plan"].get("creationRun"):
                group = owner(c,"creative_run",rid,t)
                summary = json.loads(group["plan"])
                summary.pop("copyError",None)
                c.execute("UPDATE creative_run SET plan=? WHERE id=?",(dump(summary),rid))
            c.execute("UPDATE job SET state='queued',error=NULL WHERE id=?", (id,))
    pool.submit(produce, id)
    return jsonify(id=id)


@app.get("/api/works/<id>")
def get_work(id):
    t = reqtenant()
    with db() as c:
        return jsonify(pack(c, owner(c, "work", id, t), True))


@app.post("/api/works/<id>/restore/<int:n>")
def restore(id, n):
    t = reqtenant()
    with db(True) as c:
        owner(c, "work", id, t)
        if not c.execute(
            "SELECT 1 FROM version WHERE work=? AND n=?", (id, n)
        ).fetchone():
            abort(404)
        c.execute("UPDATE work SET current=? WHERE id=?", (n, id))
    return jsonify(ok=True)


@app.get("/api/works/<id>/v/<int:n>/<mode>")
def output(id, n, mode):
    t = reqtenant()
    with db() as c:
        w = owner(c, "work", id, t)
        r = c.execute(
            "SELECT copy FROM version WHERE work=? AND n=?", (id, n)
        ).fetchone()
        if not r:
            abort(404)
    file = {
        "poster": "poster.png",
        "design-source": "poster.svg",
        "edit-source": "edit.zip",
        "open-design-source": "open-design.zip",
        "video": "video.mp4",
        "download": {"copy": "copy.txt", "poster": "poster.png", "video": "video.mp4"}[
            w["kind"]
        ],
    }.get(mode)
    path = DATA / t / "works" / id / str(n) / str(file)
    if not file or not path.exists():
        abort(404)
    if mode == "download":
        with db(True) as c:
            c.execute(
                "INSERT INTO downloads VALUES(?,?,1) ON CONFLICT(work,n) DO UPDATE SET count=count+1",
                (id, n),
            )
    suffix = "-OpenDesign.zip" if mode == "open-design-source" else path.suffix
    return send_file(
        path,
        as_attachment=mode in ("download", "design-source", "edit-source", "open-design-source"),
        download_name="响指出片-" + json.loads(r["copy"])["title"] + suffix,
        conditional=True,
    )


@app.get("/api/admin")
def admin_state():
    require_admin()
    cfg = model.settings()
    with db() as c:
        works = []
        for row in c.execute(
            """SELECT w.id,w.kind,v.n,v.copy,v.quality,r.rating,r.tags,r.metrics,
                      e.views,e.clicks,e.inquiries,e.visits,v.created,
                      (SELECT MAX(n)-1 FROM version WHERE work=w.id) AS revisions,
                      json_extract(v.copy,'$.reviewFlag') AS flag,
                      EXISTS(SELECT 1 FROM review WHERE work=w.id AND rating='不合格') AS had_issue
               FROM work w JOIN version v ON v.work=w.id AND v.n=w.current
               LEFT JOIN review r ON r.work=w.id AND r.n=v.n
               LEFT JOIN effect e ON e.work=w.id AND e.n=v.n
               ORDER BY (r.rating IS NULL) DESC, had_issue DESC, (flag IS NOT NULL) DESC,
                        revisions DESC,v.created DESC LIMIT 150"""
        ):
            val = dict(row)
            val["copy"] = json.loads(val["copy"])
            val["quality"] = json.loads(val["quality"])
            val["reviewReasons"] = [
                reason
                for reason in (
                    "曾评为不合格" if val["had_issue"] else "",
                    val["flag"],
                    f"已修改 {val['revisions']} 次" if val["revisions"] >= 2 else "",
                )
                if reason
            ]
            works.append(val)
        return jsonify(
            adminAuth={"environmentManaged": bool(os.getenv("TRUPIC_ADMIN_KEY")), "customPassword": admin_credential(c)[1]},
            modelPlatforms={**providers.overview(c), "defaults": {kind:{k:v for k,v in model.default_connection(kind).items() if k in ("url","model")} for kind in providers.KINDS}, "effective": {kind:{k:v for k,v in model.route(kind).items() if k in ("provider","url","model","protocol")} for kind in providers.KINDS}},
            modelCosts=costs.overview(c),
            modelUsage=[
                dict(r)
                for r in c.execute(
                    """SELECT platform,model,kind,COUNT(*) calls,SUM(ok) succeeded,ROUND(AVG(ms)) meanMs,
                    SUM(input_tokens) inputTokens,SUM(output_tokens) outputTokens,
                    COUNT(input_tokens) inputReports,COUNT(output_tokens) outputReports FROM model_call
                    WHERE day=? GROUP BY platform,model,kind ORDER BY calls DESC""",
                    (now()[:10],),
                )
            ],
            visualReviews=[
                {**dict(row), "report": json.loads(row["report"])}
                for row in c.execute("""SELECT j.id,j.work,j.version,j.state,j.created,j.error,j.visual_review report,
                    json_extract(j.spec,'$.kind') kind,json_extract(j.spec,'$.plan.original') brief
                    FROM job j WHERE j.visual_review IS NOT NULL
                    ORDER BY (json_extract(j.visual_review,'$.status')='blocked') DESC,j.created DESC,j.rowid DESC LIMIT 100""")
            ],
            effects=[
                dict(row)
                for row in c.execute(
                    """SELECT json_extract(v.spec,'$.plan.ruleId') strategyId,json_extract(v.spec,'$.plan.rule') strategy, COUNT(CASE WHEN e.views>0 AND e.clicks IS NOT NULL THEN 1 END) ctrSamples, ROUND(100.0*SUM(CASE WHEN e.views>0 THEN e.clicks END)/NULLIF(SUM(CASE WHEN e.views>0 AND e.clicks IS NOT NULL THEN e.views END),0),2) ctr,COUNT(*) reports,SUM(e.views) views,SUM(e.clicks) clicks,SUM(e.inquiries) inquiries,SUM(e.visits) visits FROM effect e JOIN version v ON v.work=e.work AND v.n=e.n GROUP BY strategyId,strategy"""
                )
            ],
            eventFeeds=[dict(x) for x in c.execute("SELECT id,name,url,city,category,keywords,enabled,checked,error FROM event_feed ORDER BY rowid")],
            events=[
                dict(x)
                for x in c.execute("SELECT e.* FROM event e LEFT JOIN event_feed f ON f.id=e.feed_id WHERE e.feed_id IS NULL OR f.enabled=1 ORDER BY (ends >= date('now')) DESC, CASE WHEN ends >= date('now') THEN starts END, starts DESC LIMIT 100")
            ],
            settings={
                "callsToday": {
                    r["kind"]: r["calls"]
                    for r in c.execute(
                        "SELECT kind,calls FROM provider_usage WHERE day=?",
                        (now()[:10],),
                    )
                },
                **{
                    k: cfg[k]
                    for k in (
                        "url",
                        "model",
                        "feed",
                        "license",
                        "board",
                        "pinRights",
                        "imageUrl",
                        "imageModel",
                        "visionModel",
                    )
                },
                "hasPinToken": bool(cfg["pinToken"]),
                "hasImageKey": bool(cfg["imageKey"]),
                "hasKey": bool(cfg["key"]),
                "engine": model.engine_name(),
            },
            skills=skill_library_catalog(c),
            works=works,
            cases=[
                dict(i)
                for i in c.execute(
                    "SELECT * FROM cases ORDER BY created DESC,rowid DESC"
                )
            ],
            rules=[
                {**dict(i), "tests": json.loads(i["tests"])}
                for i in c.execute(
                    "SELECT * FROM rules ORDER BY created DESC,rowid DESC"
                )
            ],
            audit=[
                dict(i)
                for i in c.execute(
                    "SELECT action,target,created FROM audit ORDER BY id DESC LIMIT 80"
                )
            ],
            jobs=[
                dict(i)
                for i in c.execute(
                    "SELECT state,COUNT(*) AS total FROM job GROUP BY state"
                )
            ],
            feedConfigured=bool(
                (cfg["feed"] and cfg["license"])
                or (cfg["board"] and cfg["pinToken"] and cfg["pinRights"])
            ),
        )


@app.get("/api/admin/preview/<id>/<int:n>/<kind>")
def admin_preview(id, n, kind):
    require_admin()
    with db() as c:
        w = c.execute("SELECT * FROM work WHERE id=?", (id,)).fetchone()
        if (
            not w
            or not c.execute(
                "SELECT 1 FROM version WHERE work=? AND n=?", (id, n)
            ).fetchone()
        ):
            abort(404)
    file = {"poster": "poster.png", "video": "video.mp4"}.get(kind)
    path = DATA / w["tenant"] / "works" / id / str(n) / str(file)
    if not file or not path.is_file():
        abort(404)
    return send_file(path)


@app.post("/api/admin/<action>")
def admin_action(action):
    require_admin()
    v = body()
    t = reqtenant()
    target = string(v.get("id"), 90)
    if action == "password":
        if os.getenv("TRUPIC_ADMIN_KEY"):
            raise ValueError("管理密码由启动环境 TRUPIC_ADMIN_KEY 指定，请在启动配置中修改并重启服务。")
        password = v.get("newPassword")
        if not isinstance(password, str) or not 8 <= len(password) <= 160 or password != password.strip():
            raise ValueError("新密码需要 8–160 位，首尾不能包含空格。")
        if password != v.get("confirmPassword"):
            raise ValueError("两次输入的新密码不一致。")
        with db(True) as c:
            if not is_admin(c):
                abort(403, description="请重新登录管理员。")
            credential, hashed = admin_credential(c)
            if not admin_matches(string(v.get("currentPassword"), 160), credential, hashed):
                abort(403, description="当前管理密码不正确。")
            encoded = generate_password_hash(password)
            c.execute("INSERT INTO admin_auth VALUES(1,?) ON CONFLICT(id) DO UPDATE SET password_hash=excluded.password_hash", (encoded,))
            audit(c, t, "修改管理密码", "")
            session["admin"] = admin_token(encoded)
        return jsonify(ok=True)
    if action == "provider-bill":
        with db(True) as c:
            costs.reconcile(c, t, v)
        return jsonify(ok=True)
    if action == "skill-version":
        with db(True) as c:
            manage_version(c, t, v)
        return jsonify(ok=True)
    if action == "event-sync":
        return jsonify(count=event_sources.refresh_source(target, t))
    if action == "event-feed":
        with db(True) as c:
            return jsonify(id=event_sources.add_source(c, t, v))
    if action == "event-toggle":
        if type(v.get("enabled")) is not bool:
            raise ValueError("请选择启用状态。")
        with db(True) as c:
            if not c.execute("""UPDATE event_feed SET enabled=?,lease='',due='',checked=NULL WHERE id=?""",
                             (v["enabled"], target)).rowcount:
                abort(404)
            audit(c, t, "启用事件来源" if v["enabled"] else "暂停事件来源", target)
        return jsonify(ok=True)
    if action == "discover":
        return jsonify(count=discover())
    if action in ("model-platform", "model-routes"):
        with db(True) as c:
            (providers.save if action == "model-platform" else providers.select)(
                c, t, v
            )
        return jsonify(ok=True)
    if action == "test-vision":
        import secrets

        cfg = model.route("vision")
        if not (cfg["model"] and cfg["url"]):
            raise ValueError("请先保存并选择视觉审核模型。")
        color = secrets.choice(["red", "blue", "green", "yellow"])
        content = image_message(
            'Which color fills the image? Respond only with JSON {"color":"red|blue|green|yellow"}.',
            Image.new("RGB", (224, 224), color),
        )
        try:
            result = model.chat_request(
                cfg, cfg["model"], [{"role": "user", "content": content}], 150, "vision"
            )
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            raise ValueError("视觉连接失败，请核对接口、密钥和模型的图片输入能力。")
        if result.get("color") != color:
            raise ValueError("模型已响应，但未正确识别测试图片。")
        return jsonify(ok=True, model=cfg["model"])
    if action == "reference-settings":
        # This screen cannot update model endpoints, credentials or routes.
        cfg = model.settings()
        for field in ("feed", "license", "board", "pinRights"):
            if field in v:
                cfg[field] = string(v.get(field), 1200)
        if v.get("pinToken"):
            cfg["pinToken"] = string(v.get("pinToken"), 1200)
        if cfg["feed"] and not (cfg["feed"].startswith("https://") and cfg["license"]):
            raise ValueError("请填写 HTTPS 来源和授权条件。")
        if cfg["board"] and not (cfg["board"].isdigit() and cfg["pinRights"] and cfg["pinToken"]):
            raise ValueError("请填写画板数字 ID、访问令牌及使用条件。")
        model.save_settings(cfg)
        with db(True) as c:
            audit(c,t,"更新参考素材来源","案例订阅与授权画板")
        return jsonify(ok=True)
    if action == "settings":
        cfg = model.settings()
        old_urls = cfg["url"], cfg["imageUrl"]
        for field in (
            "url",
            "model",
            "feed",
            "license",
            "board",
            "pinRights",
            "imageUrl",
            "imageModel",
        ):
            cfg[field] = string(v.get(field), 1200)
        if "visionModel" in v:
            cfg["visionModel"] = string(v.get("visionModel"), 180)
        if cfg.get("visionModel") and not (cfg["url"] or cfg["visionUrl"]):
            raise ValueError("请填写支持图片输入的模型接口地址。")
        if old_urls[0] != cfg["url"]:
            cfg["key"] = ""
        if old_urls[1] != cfg["imageUrl"]:
            cfg["imageKey"] = ""
        if v.get("key"):
            cfg["key"] = string(v.get("key"), 1200)
        if v.get("imageKey"):
            cfg["imageKey"] = string(v.get("imageKey"), 1200)
        if bool(cfg["imageUrl"]) != bool(cfg["imageModel"]):
            raise ValueError("图像服务地址和模型名称需同时填写。")
        if cfg["imageUrl"]:
            ep = urlparse(cfg["imageUrl"])
            if ep.scheme != "https" and not (
                ep.scheme == "http" and ep.hostname in ("localhost", "127.0.0.1", "::1")
            ):
                raise ValueError("远程图像服务须使用 HTTPS。")
        if v.get("clearKey"):
            cfg["key"] = ""
        if v.get("pinToken"):
            cfg["pinToken"] = string(v.get("pinToken"), 1200)
        if cfg["board"] and not (
            cfg["board"].isdigit() and cfg["pinRights"] and cfg["pinToken"]
        ):
            raise ValueError("请填写画板数字 ID、访问令牌及使用条件。")
        shared_vision = cfg.get("visionModel") and not cfg["visionUrl"]
        if bool(cfg["model"] or shared_vision) != bool(cfg["url"]):
            raise ValueError("模型名称和服务地址需要同时填写。")
        if cfg["url"]:
            ep = urlparse(cfg["url"])
            if ep.scheme != "https" and not (
                ep.scheme == "http" and ep.hostname in ("localhost", "127.0.0.1", "::1")
            ):
                raise ValueError("远程模型服务须使用 HTTPS。")
        if cfg["feed"] and not (cfg["feed"].startswith("https://") and cfg["license"]):
            raise ValueError("请填写 HTTPS 来源和授权条件。")
        model.save_settings(cfg)
        with db(True) as c:
            audit(c, t, "更新模型与来源配置", "服务连接")
        return jsonify(ok=True)
    if action == "test-model":
        try:
            reply, name = model.ask(
                "Return only a JSON object with ok set to true.",
                {"task": "connection test"},
                100,
            )
        except Exception:
            raise ValueError("模型未返回响应，请核对地址、模型名称及密钥。")
        if reply.get("ok") is not True:
            raise ValueError("服务已响应，模型未返回约定的 JSON 结构。")
        return jsonify(ok=True, model=name)
    with db(True) as c:
        if action == "event":
            category = string(v.get("category") or "本地活动", 20)
            if category not in ("本地活动", "节假日", "公开热点"):
                raise ValueError("请选择有效的事件类型。")
            title = string(v.get("title"), 100)
            city = string(v.get("city"), 80)
            source = string(v.get("source"), 1000)
            first, ends = (
                dt.date.fromisoformat(string(v.get("starts"), 10)),
                dt.date.fromisoformat(string(v.get("ends"), 10)),
            )
            if (
                not title
                or not city
                or urlparse(source).scheme != "https"
                or first > ends
                or not v.get("verified")
            ):
                raise ValueError("请核实并填写活动日期、地区及官方来源。")
            target = ident()
            c.execute(
                "INSERT INTO event(id,title,city,starts,ends,source,created,category) VALUES(?,?,?,?,?,?,?,?)",
                (
                    target,
                    title,
                    city,
                    first.isoformat(),
                    ends.isoformat(),
                    source,
                    now(),
                    category,
                ),
            )
        elif action == "review":
            rating = string(v.get("rating"))
            if rating not in ("优秀", "合格", "不合格"):
                raise ValueError("请选择审核结论。")
            n = int(v.get("n") or 1)
            if not c.execute(
                "SELECT 1 FROM version WHERE work=? AND n=?", (target, n)
            ).fetchone():
                abort(404)
            measures = [
                v.get(field) for field in ("views", "clicks", "inquiries", "visits")
            ]
            if any(x not in ("", None) for x in measures):
                if not string(v.get("metrics"), 250):
                    raise ValueError("请注明实际数据的来源和统计区间。")
                counts = [None if x in ("", None) else int(x) for x in measures]
                if any(x is not None and (x < 0 or x > 1_000_000_000) for x in counts):
                    raise ValueError("请填写有效的非负统计数值。")
                c.execute(
                    "INSERT OR REPLACE INTO effect VALUES(?,?,?,?,?,?,?)",
                    (target, n, *counts, string(v.get("metrics"), 250)),
                )
            c.execute(
                "INSERT OR REPLACE INTO review VALUES(?,?,?,?,?,?)",
                (
                    target,
                    n,
                    rating,
                    string(v.get("tags"), 160),
                    string(v.get("metrics"), 250),
                    now(),
                ),
            )
        elif action == "case":
            title = string(v.get("title"), 150)
            source = string(v.get("source"), 1000)
            license = string(v.get("license"), 220)
            lesson = string(v.get("lesson"), 300)
            issue = string(v.get("issue"), 160)
            cat = string(v.get("category"))
            kind = string(v.get("kind"))
            if (
                not all((title, source, license, lesson))
                or urlparse(source).scheme not in ("http", "https")
                or cat not in ("优秀案例", "反面案例", "创意方法")
                or kind not in ("图片", "视频", "文案")
            ):
                raise ValueError("请补全案例名称、来源网址、授权条件和拆解方法。")
            if cat == "反面案例" and not issue:
                raise ValueError("请标注反面案例的具体问题。")
            if c.execute("SELECT 1 FROM cases WHERE source=?", (source,)).fetchone():
                raise ValueError("这个来源已经收录。")
            target = ident()
            c.execute(
                "INSERT INTO cases(id,title,source,license,kind,category,lesson,issue,status,created,tags,scenario) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    target,
                    title,
                    source,
                    license,
                    kind,
                    cat,
                    lesson,
                    issue,
                    "pending",
                    now(),
                    string(v.get("tags"), 160),
                    string(v.get("scenario"), 200),
                ),
            )
        elif action == "approve":
            r = c.execute("SELECT * FROM cases WHERE id=?", (target,)).fetchone()
            if not r:
                abort(404)
            if r["status"] != "pending":
                raise ValueError("该案例已经审核入库。")
            lesson = string(v.get("lesson") or r["lesson"], 300)
            if not lesson:
                raise ValueError("请先填写可迁移的创意方法。")
            c.execute(
                "UPDATE cases SET lesson=?,tags=?,scenario=?,status='approved' WHERE id=?",
                (
                    lesson,
                    string(v.get("tags", r["tags"]), 160),
                    string(v.get("scenario", r["scenario"]), 200),
                    target,
                ),
            )
        elif action == "rule":
            name = string(v.get("name"), 80)
            method = string(v.get("method"))
            reason = string(v.get("reason"), 220)
            if method not in METHODS or not name or not reason:
                raise ValueError("请填写版本名称、更新原因和创意方法。")
            target = ident()
            case_id = string(v.get("case_id"), 80)
            if (
                case_id
                and not c.execute(
                    "SELECT 1 FROM cases WHERE id=? AND status='approved' AND category!='反面案例'",
                    (case_id,),
                ).fetchone()
            ):
                raise ValueError("请选择已审核入库的正面方法。")
            lesson = (
                c.execute("SELECT lesson FROM cases WHERE id=?", (case_id,)).fetchone()
                if case_id
                else None
            )
            tests = run_tests(
                {
                    "id": target,
                    "name": name,
                    "method": method,
                    "lesson": lesson[0] if lesson else "",
                }
            )
            c.execute(
                "INSERT INTO rules(id,name,method,reason,tests,status,percent,created,case_id) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    target,
                    name,
                    method,
                    reason,
                    dump(tests),
                    "tested" if all(x["ok"] for x in tests) else "failed",
                    0,
                    now(),
                    case_id,
                ),
            )
        elif action == "retrieval":
            r = c.execute(
                """SELECT r.tests,r.status,c.status approved,c.category FROM rules r JOIN cases c ON c.id=r.case_id WHERE r.id=?""",
                (target,),
            ).fetchone()
            enabled = v.get("enabled")
            if type(enabled) is not bool or not r:
                raise ValueError("请选择已关联案例的策略。")
            if enabled:
                tests = json.loads(r["tests"])
                if (
                    r["status"] == "failed"
                    or r["approved"] != "approved"
                    or r["category"] == "反面案例"
                    or not tests
                    or not all(x["ok"] for x in tests)
                ):
                    raise ValueError("只有通过固定测试且已审核的方法可用于检索。")
            c.execute("UPDATE rules SET retrievable=? WHERE id=?", (enabled, target))
        elif action in ("pilot", "release", "rollback"):
            r = c.execute("SELECT * FROM rules WHERE id=?", (target,)).fetchone()
            if (
                not r
                or r["status"] == "failed"
                or (
                    target != "baseline"
                    and not all(x["ok"] for x in json.loads(r["tests"]))
                )
            ):
                raise ValueError("固定测试未通过，无法启用。")
            if action == "pilot":
                if r["status"] == "live":
                    raise ValueError("此版本已经全量启用。")
                c.execute(
                    "UPDATE rules SET status='archived',percent=0 WHERE status='pilot'"
                )
                c.execute(
                    "UPDATE rules SET status='pilot',percent=10 WHERE id=?", (target,)
                )
            else:
                c.execute(
                    "UPDATE rules SET status='archived',percent=0 WHERE status IN ('live','pilot')"
                )
                c.execute(
                    "UPDATE rules SET status='live',percent=100 WHERE id=?", (target,)
                )
        else:
            abort(404)
        audit(
            c,
            t,
            {
                "event": "核实营销事件",
                "retrieval": "启用方法检索" if v.get("enabled") else "停用方法检索",
                "review": "作品抽查",
                "case": "添加案例",
                "approve": "审核入库",
                "rule": "测试新策略",
                "pilot": "灰度启用",
                "release": "全量启用",
                "rollback": "版本回退",
            }[action],
            target,
        )
    return jsonify(ok=True)


@app.get("/")
@app.get("/<path:path>")
def site(path=""):
    dist = ROOT / "dist"
    if not (dist / "index.html").exists():
        return "请先运行 npm run build，或使用 npm run dev。", 503
    if path.startswith("api/"):
        abort(404)
    if path and (dist / path).is_file():
        return send_from_directory(dist, path)
    return send_from_directory(dist, "index.html")


register_bundles(app, globals())
register_creations(app, globals())
register_model_tools(app, globals())


def start():
    with db(True) as c:
        for j in c.execute(
            "SELECT id,worker_pid FROM job WHERE state='running'"
        ).fetchall():
            try:
                if not j["worker_pid"]:
                    raise ProcessLookupError()
                os.kill(j["worker_pid"], 0)
            except ProcessLookupError:
                c.execute("UPDATE job SET state='queued' WHERE id=?", (j["id"],))
        pending = [
            row[0] for row in c.execute("SELECT id FROM job WHERE state='queued'")
        ]
    for id in pending:
        pool.submit(produce, id)

    def sync():
        import time

        last_sync = 0
        last_week = None
        while True:
            event_sources.refresh_due()
            cfg = model.settings()
            week = dt.date.today().isocalendar()[:2]
            if last_week != week:
                with db(True) as c:
                    for merchant in c.execute(
                        "SELECT id,profile FROM merchant"
                    ).fetchall():
                        weekly(
                            c,
                            merchant["id"],
                            json.loads(merchant["profile"]),
                            history(c, merchant["id"]),
                        )
                last_week = week
            configured = (cfg["feed"] and cfg["license"]) or (
                cfg["board"] and cfg["pinToken"] and cfg["pinRights"]
            )
            if configured and time.time() - last_sync > 86400:
                try:
                    discover()
                    last_sync = time.time()
                except Exception:
                    logging.exception("Reference feed unavailable")
                    last_sync = time.time() - 82800
            time.sleep(60)

    threading.Thread(target=sync, daemon=True).start()
    from waitress import serve

    port = int(os.getenv("PORT", 7341))
    print(f"响指出片 Trupic  http://127.0.0.1:{port}", flush=True)
    serve(app, host=os.getenv("TRUPIC_HOST", "127.0.0.1"), port=port, threads=8)


if __name__ == "__main__":
    start()
