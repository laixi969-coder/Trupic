import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from .production_queue import ProductionQueue
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

from . import model, moments, providers, personal_agent, merchant_blind
from .copy_choices import apply_choice, choices_for_quote, selected_copy
from .background import make_scene
from .creative import (
    CASES,
    METHODS,
    unconfirmed_number,
    RISK,
    draft_copy,
    generate_copy,
    prepare,
)
from .governance import active_rule, discover, run_tests, retrieve_method, validate_pinterest_settings
from .media import ROOT, SIZES, inspect_upload, photo_layout_features, render
from .store import DATA, TRIAL_NOTE, audit, db, dump, grant_trial, ident, init, now, secret, tenant_new
from . import object_storage, region_edit, reference_assets, event_sources, costs, pricing, work_history, revisions, wallet, commerce, model_admission, growth, coupons, staff
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
from .campaign import long_form, storyboard
from .shot_detail import merchant_detail
from .prompt_agent import apply_poster_layout, elevate_for_production, full_poster_prompt, optimize
from .product_bundle import qualified_cutout, register as register_bundles
from .auto_creation import register as register_creations
from .auto_pipeline import shared_copy
from .voice import register as register_voice
from .model_tools import register as register_model_tools
from .skill_library import attach as attach_skills, catalog as skill_library_catalog, effective_versions, manage_version, import_package
from .visual_review import (
    FIDELITY,
    LayoutOverflow,
    classify_repair,
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
    SESSION_REFRESH_EACH_REQUEST=False,
    PERMANENT_SESSION_LIFETIME=dt.timedelta(days=180),
)
quotes = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="trupic-creative-quote")
COST = {key: pricing.DEFAULT[key] for key in pricing.KINDS}
LABEL = {"copy": "推广文案", "poster": "营销海报", "video": "宣传短片"}
ADMIN = os.getenv("TRUPIC_ADMIN_KEY") or secret("admin.key")
init()
with db(True) as c:
    c.execute("CREATE TABLE IF NOT EXISTS admin_auth (id INTEGER PRIMARY KEY CHECK(id=1), password_hash TEXT NOT NULL)")
pool = ProductionQueue(int(os.getenv("TRUPIC_JOB_WORKERS", "2")))
# Jobs being produced by this process. A running job outside this set has lost its worker.
ACTIVE = set()
ACTIVE_LOCK = threading.Lock()
RECOVERIES = {}
SIGNIN_FAILURES = {}
SIGNIN_LIMIT = int(os.getenv("TRUPIC_SIGNIN_FAILURES") or 20)


def blocked_signin(key):
    """Slow down password guessing: failures per source and account within ten minutes."""
    if not SIGNIN_LIMIT:
        return False
    recent = [at for at in SIGNIN_FAILURES.get(key, []) if at > time.monotonic() - 600]
    if recent:
        SIGNIN_FAILURES[key] = recent
    else:
        SIGNIN_FAILURES.pop(key, None)
    return len(recent) >= SIGNIN_LIMIT


def fail_signin(key):
    SIGNIN_FAILURES.setdefault(key, []).append(time.monotonic())


def body():
    return request.get_json(silent=True) or {}


def string(val, limit=500):
    return val.strip()[:limit] if isinstance(val, str) else ""


def client_source():
    """Client address for daily trial quotas.

    The forwarded address is trusted only when TRUPIC_TRUST_PROXY=1, i.e. the operator
    runs a reverse proxy that overwrites X-Forwarded-For.
    """
    if os.getenv("TRUPIC_TRUST_PROXY") == "1":
        forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.remote_addr or ""


def reqtenant(trial=True):
    if not session.get("tenant"):
        t = ident()
        with db(True) as c:
            tenant_new(c, t, client_source() if trial else None)
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
        if not is_admin(c) and not staff.permitted(staff.role(c),request.path,request.method):
            abort(403, description="当前账号没有此项管理权限。")


def owner(c, table, id, t):
    row = c.execute(
        f"SELECT * FROM {table} WHERE id=? AND tenant=?", (id, t)
    ).fetchone()
    if not row or (table == "work" and work_history.hidden(c, id)):
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
           WHERE w.tenant=? AND NOT EXISTS (SELECT 1 FROM work_trash h WHERE h.work=w.id) ORDER BY w.created DESC,w.rowid DESC LIMIT 35""",
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
        versions.append(
            dict(
                n=n,
                created=r["created"],
                layoutSuggestion=layout_alternative(spec["plan"], copy, w["kind"])
                if all_versions and w["kind"] != "copy"
                else None,
                **copy,
                brief=spec["plan"]["original"],
                plan=spec["plan"],
                quality=json.loads(r["quality"]),
                asset=spec["asset"],
                ratio=spec["ratio"],
                poster=base + "/poster",
                offerPoster=base + "/offer-poster" if copy.get("merchantOfferProof") and w["kind"] == "video" else None,
                post=base + "/post" if w["kind"] == "video" else None,
                download=base + "/download",
                designSource=base + "/design-source"
                if w["kind"] == "poster"
                and (folder / "poster.svg").is_file()
                else None,
                editSource=base + "/edit-source"
                if w["kind"] == "video" and (folder / "edit.zip").is_file()
                else None,
                subtitles=base + "/subtitles" if copy.get("narration") else None,
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
    with db(True) as c:
        commerce.issue_due(c,t)
        wallet.expire(c,t)
        # Grant a withheld trial as soon as the daily quota allows, before the balance is read.
        trial_ok = grant_trial(c, t, client_source())
        m = c.execute("SELECT * FROM merchant WHERE id=?", (t,)).fetchone()
        prof = json.loads(m["profile"])
        works = [
            pack(c, w)
            for w in c.execute(
                "SELECT * FROM work WHERE tenant=? AND id NOT IN (SELECT work FROM work_trash) ORDER BY created DESC,rowid DESC",
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
                "SELECT id,state,work,error,created,json_extract(spec,'$.plan.autoCreation') AS autoCreation FROM job WHERE tenant=? AND work NOT IN (SELECT work FROM work_trash) AND state IN ('queued','running','failed') ORDER BY created DESC,rowid DESC LIMIT 15",
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
            workspace=t,
            personalAgent=personal_agent.enabled(t),
            admin=is_admin(c) or bool(staff.role(c)),
            credits=pricing.available(c, t),
            # Shown only when the daily network quota actually withheld the trial.
            trialNote="" if trial_ok else TRIAL_NOTE,
            works=works,
            assets=assets,
            cases=CASES,
            recs=recs,
            ledger=ledger,
            reservations=[dict(r) for r in c.execute("""SELECT job,action,SUM(amount) amount,created FROM credit_event
                WHERE tenant=? GROUP BY job,action,created ORDER BY MAX(id) DESC LIMIT 80""",(t,))],
            jobs=jobs,
            prices=pricing.current(c),
            videoDurations=[15,30,45] if commerce.subscription(c,t) else [15],
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
    tags = v.get("industryTags")
    if tags is not None:
        if not isinstance(tags, list) or len(tags) > 10 or any(not isinstance(tag, str) or not 0 < len(tag.strip()) <= 24 for tag in tags):
            raise ValueError("行业最多可选 10 项，每项不超过 24 字。")
        p["industryTags"] = list(dict.fromkeys(tag.strip() for tag in tags))
        p["industry"] = "、".join(p["industryTags"])
    else:
        p["industryTags"] = [tag for tag in p["industry"].split("、") if tag]
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
    # Signing in must not spend a trial on a workspace the visitor is about to leave.
    t = reqtenant(trial=action not in ("login", "register"))
    v = body()
    login = string(v.get("login"), 64).lower()
    pw = string(v.get("password"), 160)
    if action == "logout":
        session.clear()
        return jsonify(ok=True)
    if action == "admin":
        source = (request.remote_addr, "admin")
        if blocked_signin(source):
            abort(429, description="尝试次数过多，请十分钟后再试。")
        with db(True) as c:
            credential, hashed = admin_credential(c)
            if not admin_matches(pw, credential, hashed):
                fail_signin(source)
                abort(403, description="管理密码不正确；首次登录请使用本机初始管理密钥，它与商家账号密码不同。")
            SIGNIN_FAILURES.pop(source, None)
            session["admin"] = admin_token(credential)
            audit(c, t, "管理登录", "")
        return jsonify(ok=True)
    if not login or len(pw) < 8:
        raise ValueError("请填写账号，并使用至少 8 位的密码。")
    entering = None
    if action == "login" and blocked_signin((request.remote_addr, "account", login)):
        abort(429, description="尝试次数过多，请十分钟后再试。")
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
            # Binding an account is the moment a withheld trial may be granted.
            grant_trial(c, t, client_source())
            growth.bind_link(c,t,string(v.get("invite"),64),string(v.get("channel"),64),new=True)
        elif action == "login":
            r = c.execute("SELECT * FROM merchant WHERE login=?", (login,)).fetchone()
            if not r or not check_password_hash(r["password"], pw):
                fail_signin((request.remote_addr, "account", login))
                abort(401, description="账号或密码不正确。")
            # A rejected promotion link must not sign the merchant out of the current workspace.
            growth.bind_link(c,r["id"],string(v.get("invite"),64),string(v.get("channel"),64))
            grant_trial(c, r["id"], client_source())
            entering = r["id"]
        else:
            abort(404)
    SIGNIN_FAILURES.pop((request.remote_addr, "account", login), None)
    if entering:
        session.clear()
        session["tenant"] = entering
        session.permanent = True
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
            object_storage.enqueue(c,folder,{"original.png",info["file"]})
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
            """SELECT 1 FROM job WHERE tenant=? AND (json_extract(spec,'$.asset')=? OR
               EXISTS (SELECT 1 FROM json_each(spec,'$.plan.references') WHERE json_extract(value,'$.id')=?)) LIMIT 1""",
            (t,id,id),
        ).fetchone():
            raise ValueError("已有任务引用此素材，需保留以供版本回看。")
        object_storage.forget(c,DATA / t / "assets" / id)
        c.execute("DELETE FROM asset WHERE id=?", (id,))
    shutil.rmtree(DATA / t / "assets" / id, ignore_errors=True)
    return jsonify(ok=True)


def plan_spec(c, t, v, *, original_photo=False, agent_profile=None):
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
            and not (original_photo and policy == "original")
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
    if agent_profile is not None:
        prof = agent_profile
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
    promoted = string(v.get("promotedItem"), 80)
    if promoted:
        prof = {**prof, "product": promoted}
    rule = active_rule(c, t)
    retrieved = retrieve_method(c, brief, prof)
    if retrieved:
        rule = {**rule, "method": retrieved["method"]}
    plan = prepare(
        brief,
        prof,
        [] if agent_profile is not None else history(c, t),
        rule,
        string(v.get("reference")),
        string(v.get("facts"), 250),
    )
    ref = c.execute(
        "SELECT c.id,c.title,c.lesson,c.kind,c.source,c.license FROM cases c JOIN rules r ON c.id=r.case_id WHERE r.id=? AND c.status='approved' AND c.category!='反面案例'",
        (plan["ruleId"],),
    ).fetchone()
    plan["promotedItem"] = promoted or prof.get("product", "")
    plan["industryTags"] = prof.get("industryTags", [prof["industry"]] if prof.get("industry") else [])
    plan["businessGoal"] = string(v.get("businessGoal"), 40)
    if plan["businessGoal"]:
        plan["goal"] = plan["businessGoal"]
        plan["briefGoal"] = plan["businessGoal"]
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
        if asset and kind == "poster":
            filename = "original.png" if policy == "original" else json.loads(a["info"])["file"]
            plan["photoFeatures"] = photo_layout_features(DATA / t / "assets" / asset / filename)
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


@app.post("/api/copy-options")
def copy_options():
    v = body()
    return jsonify(options=choices_for_quote(quotes, string(v.get("quote"), 1_000_000), reqtenant(), v.get("previousTitles")))


@app.post("/api/preview")
def preview():
    t = reqtenant()
    with db() as c:
        s = plan_spec(c, t, body())
        cost = pricing.snapshot(s, pricing.current(c))
    preflight(s, DATA / t / "assets")
    optimize(s)
    poster_prompt = None
    if s["kind"] == "poster":
        draft = draft_copy(s["plan"])
        apply_poster_layout(s["plan"], draft)
        poster_prompt = full_poster_prompt(s["plan"], draft)
    return jsonify(
        plan=s["plan"],
        fullPosterPrompt=poster_prompt,
        requiresCopyChoice=s["kind"] == "poster",
        cost=cost,
        kind=s["kind"],
        ratio=s["ratio"],
        engine=model.engine_name() or "未启用文字模型",
        quote=quotes.dumps({"tenant": t, "spec": s, "cost": cost}),
    )


def enough(c, t, cost):
    commerce.issue_due(c,t)
    wallet.expire(c,t)
    if pricing.available(c, t) < cost:
        raise ValueError("可用积分不足。")


def moment_spec(c, tenant, request):
    asset = string(request.get("asset"), 60)
    note = request.get("note", "")
    if not asset:
        raise ValueError("请先拍照或选一张照片。")
    if not isinstance(note, str) or len(note) > 140:
        raise ValueError("补充说明最多 140 字。")
    note = note.strip()
    row = owner(c, "asset", asset, tenant)
    folder = DATA / tenant / "assets" / asset
    info = {**json.loads(row["info"]), "path": folder / "subject.png"}
    cutout = qualified_cutout(info, True)
    ratio = request.get("ratio", "portrait")
    if ratio not in ("portrait", "story"):
        raise ValueError("朋友圈画幅请选择 3:4 或 9:16。")
    brief = "用实拍商品做今天的朋友圈图文。" + note
    spec = plan_spec(c, tenant, dict(
        kind="poster", brief=brief, facts=note, asset=asset,
        assetMode="processed" if cutout else "original", assetConfirmed=cutout,
        posterStyle="auto", ratio=ratio, resolution=1080, dpi=72, source="今天的朋友圈",
    ), original_photo=True)
    spec["plan"]["moment"] = dict(note=note, workflowVersion=2)
    if cutout:
        spec["plan"]["moment"]["roundSubject"] = moments.round_subject(info["path"])
    return spec


def enqueue(t, v, work=None, *, moment=False, agent_reserve=None):
    key = string(v.get("requestKey"), 90)
    if not key or (key.startswith("agent:") and not agent_reserve):
        raise ValueError("缺少有效请求标识，请刷新后再试。")
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
            try:
                q = quotes.loads(v.get("quote") or "", salt="revision", max_age=1800)
            except BadSignature:
                raise ValueError("请先查看并确认修改报价。")
            if q["tenant"] != t or q["work"] != work:
                abort(403)
            if (agent_reserve or q["action"] == "h3-background") and q.get("currentAtQuote") != w["current"]:
                abort(409, description="原作品已有新版本，请刷新修改报价。")
            if type(v.get("confirmedCost")) is not int or v["confirmedCost"] != q["cost"] or v.get("confirmed") is not True:
                raise ValueError("请确认本次修改的总积分。")
            r = c.execute("SELECT spec,copy FROM version WHERE work=? AND n=?", (work,q["base"])).fetchone()
            s = json.loads(r["spec"])
            s["plan"].pop("agentTask", None)
            s.pop("filmSourceVersion", None)
            s.pop("backgroundSourceVersion", None)
            s.pop("backgroundApproval", None)
            s["plan"].pop("videoProviderReceipt", None)
            s.pop("endingTake", None)
            cost = q["cost"]
            s["pricingSnapshot"] = q["pricingSnapshot"]
            nxt = c.execute("SELECT MAX(n)+1 FROM version WHERE work=?", (work,)).fetchone()[0]
            s["variant"] = nxt - 1
            revisions.prepare(s, json.loads(r["copy"]), q["action"], q.get("ratio"), v.get("option", 0),q.get("instruction"),q.get("field"),q.get("region"))
            s.pop("reuseCloudSet", None)
            if q["action"] != "h3-background" and s["plan"].get("videoMotion") == "economy":
                s["reuseCloudSet"] = True
            if q["action"] == "h3-background":
                from .video_api import economy_config
                approval = hashlib.sha256(v["quote"].encode()).hexdigest()
                if c.execute("SELECT 1 FROM job WHERE tenant=? AND work=? AND json_extract(spec,'$.backgroundApproval')=?",
                             (t, work, approval)).fetchone():
                    abort(409, description="此背景报价已提交，请查看原任务或从原任务重试。")
                economy_config()
                s["variant"] = json.loads(r["spec"])["variant"]
                s["backgroundSourceVersion"] = q["base"]
                s["backgroundApproval"] = approval
            if q.get("rewrite"):
                s["replacement"] = q["rewrite"]
            if q.get("reuseFilm"):
                s["variant"] = json.loads(r["spec"])["variant"]
                s["filmSourceVersion"] = q["base"]
            if q.get("endingPreview") and not q.get("endingTake"):
                raise ValueError("请先试听并选择片尾读法。")
            if q.get("endingTake"):
                if not agent_reserve:
                    raise ValueError("请在营销助理中确认试听后的报价。")
                s["endingTake"] = q["endingTake"]
            if q["action"] == "region":
                s["variant"] = json.loads(r["spec"])["variant"]
                s["regionEdit"] = dict(work=work,version=q["base"],box=q["region"],instruction=q["instruction"])
            if q["action"] == "ratio" or q.get("duplicate"):
                s["plan"]["sourceVersion"] = {"work": work, "version": q["base"]}
                work, nxt = ident(), 1
        else:
            if moment:
                s = moment_spec(c, t, v)
            elif v.get("quote"):
                try:
                    q = quotes.loads(v["quote"], max_age=1800)
                except BadSignature:
                    raise ValueError("这份方案已过期，请返回重新分析。")
                if q["tenant"] != t:
                    abort(403)
                if "spec" not in q:
                    raise ValueError("请使用单项作品的创作方案。")
                s = q["spec"]
                check_topic(c, t, s["plan"].get("topic"))
                if s["asset"]:
                    owner(c, "asset", s["asset"], t)
            else:
                s = plan_spec(c, t, v)
            if s["kind"] == "poster" and not moment:
                apply_choice(s, selected_copy(quotes, v))
            cost = pricing.quoted_cost(s) if v.get("quote") and not moment else pricing.snapshot(s, pricing.current(c))
            work = ident()
            nxt = 1
            if moment and (type(v.get("confirmedCost")) is not int or v["confirmedCost"] != cost or v.get("confirmed") is not True):
                raise ValueError("本次用量已更新，请查看按钮上的积分后再制作。")
            if cost and (v.get("confirmedCost") != cost or not v.get("confirmed")):
                raise ValueError("请确认本次积分用量后再制作。")
        enough(c, t, cost)
        id = ident()
        if agent_reserve:
            agent_reserve(c, id, s)
        c.execute(
            "INSERT INTO job(id,tenant,request_key,spec,state,cost,work,version,error,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (id, t, key, dump(s), "queued", cost, work, nxt, None, now()),
        )
        wallet.reserve(c,t,id,cost)
    pool.submit(produce, id)
    return dict(id=id, state="queued", work=work)


@app.get("/api/moments/price")
def moment_price():
    tenant = reqtenant()
    with db() as c:
        return jsonify(cost=pricing.current(c)["poster"], workspace=tenant, personalAgent=personal_agent.enabled(tenant))


@app.post("/api/moments")
def create_moment():
    return jsonify(enqueue(reqtenant(), body(), moment=True))


@app.post("/api/jobs")
def create_job():
    return jsonify(enqueue(reqtenant(), body()))


@app.post("/api/works/<id>/revision-quote")
def revision_quote(id):
    return jsonify(make_revision_quote(reqtenant(), id, body()))


def make_revision_quote(t, id, v):
    with db() as c:
        w = owner(c, "work", id, t)
        base = v.get("base", w["current"])
        r = c.execute("SELECT spec,copy FROM version WHERE work=? AND n=?", (id, base)).fetchone()
        if not r:
            abort(404)
        spec, cp = json.loads(r["spec"]), json.loads(r["copy"])
        action = v.get("action", "revision")
        options = revisions.short_options(cp) if action == "shorten" else []
        if action == "moment-copy" and "moment" in spec["plan"]:
            options = moments.drafts(spec["plan"])
        instruction = v.get("instruction")
        previous_offer = spec["plan"].get("merchantOffer")
        if v.get("product") and v["product"] != (previous_offer or {}).get("product"):
            raise ValueError("这次写的商品名与原作品不同，请选择对应商品的作品。")
        wants_ending = v.get("endingPreview") is True or action == "ending"
        if wants_ending and (spec["kind"] != "video" or not spec["plan"].get("productNarration") or not cp.get("narration")):
            raise ValueError("请选择一条已交付的逐镜口播商品短片。")
        if action == "edit":
            instruction = revisions.resolve_instruction(spec,cp,instruction,v.get("field"))
        revisions.prepare(spec, cp, action, v.get("ratio"),instruction=instruction,field=v.get("field"),region=v.get("region"))
        offer = spec["plan"].get("merchantOffer")
        reuse_film = bool(spec["kind"] == "video" and cp.get("narration") and
                          (wants_ending or (action == "edit" and offer and offer != previous_offer)))
        film_scope = None
        if action == "h3-background":
            from .video_api import economy_config
            from .film_background import verify_archive
            if wants_ending or v.get("duplicate"):
                raise ValueError("动态背景对照需保留原音轨和同一作品。")
            economy_config()
            verify_archive(DATA / t / "works" / id / str(base) / "edit.zip", cp["storyboard"], spec["plan"]["output"])
            film_scope = dict(storyboard=cp["storyboard"], productNarration=True, merchantOffer=offer,
                              videoMotion="economy", deliveries=["仅替换动态背景，沿用商品图、口播、字幕及价格"])
        if reuse_film:
            film_scope = dict(storyboard=storyboard(spec["plan"], spec["replacement"]), productNarration=True,
                              merchantOffer=offer, previousOffer=previous_offer, voiceRevision=wants_ending,
                              deliveries=["短片、活动海报、字幕、配文"] if offer else ["短片、字幕、配文"])
        rewrite = None
        if action == "revision":
            rewrite = generate_copy(spec["plan"], revision_note="在保留事实与指定标题的前提下，换一个创意角度。上一稿标题：" + cp["title"])
            if rewrite.get("reviewFlag"):
                raise ValueError(rewrite.get("callError") or rewrite.get("revisionNote") or rewrite["reviewFlag"])
            spec["replacement"] = rewrite
        cost = pricing.snapshot(spec, pricing.current(c), "revision")
        quote = quotes.dumps(dict(tenant=t, work=id, base=base, currentAtQuote=w["current"], action=action, rewrite=rewrite, ratio=v.get("ratio"),
                                  **({"approvalId": ident()} if action == "h3-background" else {}),
                                  reuseFilm=reuse_film, endingPreview=wants_ending,
                                  pricingSnapshot=spec["pricingSnapshot"], cost=cost, instruction=instruction,field=v.get("field"),region=v.get("region"),duplicate=v.get("duplicate") is True), salt="revision")
        return dict(cost=cost, options=options, quote=quote, filmScope=film_scope,
                    changes={k:spec["replacement"].get(k) for k in ("title","body","cta","offer","terms")} if action in ("edit","revision","ending") else None)


@app.post("/api/works/<id>/revise")
def revise(id):
    return jsonify(enqueue(reqtenant(), body(), id))


def produce(id):
    from .store import model_job
    token = model_job.set(id)
    with ACTIVE_LOCK:
        ACTIVE.add(id)
    try:
        return produce_job(id)
    finally:
        with ACTIVE_LOCK:
            ACTIVE.discard(id)
        model_job.reset(token)


def worker_alive(pid, created=None):
    """A recycled process ID must not keep a job from an earlier process running forever."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    if created is None:
        return True
    try:
        started = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
            env={**os.environ, "LC_ALL": "C"}, timeout=5,
        ).stdout.strip()
        boot = dt.datetime.strptime(started, "%a %b %d %H:%M:%S %Y").astimezone(dt.UTC)
        return boot <= dt.datetime.fromisoformat(created)
    except (OSError, ValueError, subprocess.SubprocessError):
        return True


def recover_jobs():
    """Requeue running jobs whose worker died before settling. Credits stay reserved once."""
    with db() as c:
        rows = c.execute(
            "SELECT id,tenant,work,cost,worker_pid,created FROM job WHERE state='running'"
        ).fetchall()
        with ACTIVE_LOCK:
            tracked = set(RECOVERIES)
        if tracked:
            # Only a finished job clears its recovery count; a requeued job keeps it.
            marks = ",".join("?" for _ in tracked)
            finished = {
                r[0]
                for r in c.execute(
                    f"SELECT id FROM job WHERE state IN ('complete','failed') AND id IN ({marks})",
                    tuple(tracked),
                )
            }
            with ACTIVE_LOCK:
                for id in finished:
                    RECOVERIES.pop(id, None)
    with ACTIVE_LOCK:
        active = set(ACTIVE)
    recovered = []
    for j in rows:
        if j["id"] in active:
            continue
        if j["worker_pid"] != os.getpid() and worker_alive(j["worker_pid"], j["created"]):
            continue
        if RECOVERIES.get(j["id"], 0) >= 2:
            # The same job keeps losing its worker: release the reservation instead of re-running.
            with db(True) as c:
                if c.execute("UPDATE job SET state='failed',error=?,stage=NULL WHERE id=? AND state='running'",
                             ("制作中断，预占积分已退回。请重试。", j["id"])).rowcount:
                    wallet.finish(c, j["tenant"], j["id"], False)
            RECOVERIES.pop(j["id"], None)
            continue
        RECOVERIES[j["id"]] = RECOVERIES.get(j["id"], 0) + 1
        with db(True) as c:
            if c.execute("UPDATE job SET state='queued',stage=NULL WHERE id=? AND state='running'", (j["id"],)).rowcount:
                recovered.append(j["id"])
    for id in recovered:
        pool.submit(produce, id)
    return recovered


def produce_job(id):
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

    def stage(message):
        with db(True) as c:
            c.execute("UPDATE job SET stage=? WHERE id=?", (message, id))

    try:
        stage("正在准备素材和文案")
        locked_background = s.get("backgroundSourceVersion")
        if not locked_background and ((p.get("autoCreation") and model.route("vision")["model"]) or (not p.get("bundleRole") and not p.get("autoCreation"))):
            preflight(s, DATA / t / "assets")
        cached_copy = j["copy_checkpoint"]
        if (cached_copy and p.get("autoCreation") and not s.get("copySelected")
                and json.loads(cached_copy).get("engine") == "本地创意规则"):
            cached_copy = None
        refine_preview = (p.get("autoCreation") and n == 1 and not cached_copy
                          and not p.get("promptOptimizationAttempted") and model.route("text")["model"])
        if not p.get("promptBrief") or refine_preview:
            if "moment" in p:
                moments.read_photo(p)
            optimize(s)
            p["promptOptimizationAttempted"] = True
            with db(True) as c:
                c.execute("UPDATE job SET spec=? WHERE id=?", (dump(s), id))
        if "moment" in p and not (cached_copy or s.get("replacement") or p["moment"].get("drafts")):
            moments.prepare_drafts(s, t)
        cp = (
            json.loads(cached_copy)
            if cached_copy
            else shared_copy(s) if p.get("autoCreation") and n == 1 else s.get("replacement")
            or (moments.first_copy(p) if "moment" in p else generate_copy(p, 0))
        )
        if cp.get("reviewFlag") and not cp.get("engine"):
            raise ValueError(cp.get("callError") or cp.get("revisionNote") or cp["reviewFlag"])
        ap = None
        if s["asset"]:
            with db() as c:
                a = owner(c, "asset", s["asset"], t)
            filename = "original.png" if s.get("assetMode") == "original" else json.loads(a["info"])["file"]
            ap = DATA / t / "assets" / s["asset"] / filename
        if n == 1 and s["kind"] in ("poster", "video") and not s.get("regionEdit"):
            elevate_for_production(s, cp)
        if s["kind"] == "video" and not locked_background:
            if not (p.get("agentTask") and s.get("copySelected")) and (longer := long_form(p, cp)):
                cp["longForm"] = longer
            cp["storyboard"] = storyboard(p, cp, ap)
        if s["kind"] == "poster" and p.get("posterArt") and p.get("output"):
            if n == 1 or ("moment" in p and not s.get("regionEdit") and not p.get("layoutOverride")):
                apply_poster_layout(p, cp)
            cp["fullPosterPrompt"] = full_poster_prompt(p, cp)
            if "moment" in p:
                p["moment"]["headline"] = cp["title"]
        known = (
            p["original"]
            + " "
            + p["facts"]
            + " "
            + json.dumps(p["profile"], ensure_ascii=False)
        )
        words = cp["title"] + " " + cp["body"] + " " + cp["cta"]
        if p.get("productNarration"):
            words += " " + " ".join(shot["narration"] for shot in cp["storyboard"])
        if s["kind"] == "video" and cp["storyboard"][1].get("evidence"):
            words += " " + cp["storyboard"][1]["line"]
            known += " " + p.get("markedDetail", {}).get("label", "")
        words += " " + " ".join(cp.get("longForm", {}).values())
        if RISK.search(words) or unconfirmed_number(words, known):
            raise ValueError("检测到未经确认的经营声明，请补充事实后重新创作。")
        if not cached_copy:
            with db(True) as c:
                c.execute("UPDATE job SET copy_checkpoint=?,spec=? WHERE id=?", (dump(cp), dump(s), id))
        if s["kind"] != "copy":
            stage("正在生成视频画面" if s["kind"] == "video" else "正在准备海报画面")
        # "换一张" on a poster that has no real photo draws a new scene; the copy stays.
        new_scene = bool(s["kind"] == "poster" and not ap and p.get("visualSource") == "concept"
                         and p.get("layoutOverride") and s.get("variant", 0) > 0)
        scene = f"concept-{s['variant']}" if new_scene else "concept"
        if s.get("filmSourceVersion"):
            background, visual_engine = None, "复用已交付净画面"
        elif s.get("reuseCloudSet"):
            frames = Path(p.get("videoBackground") or "")
            if not frames.is_relative_to(DATA / t / "works") or not (frames / "001.jpg").is_file():
                raise ValueError("原动态背景文件不可用，请恢复原素材，或重新确认生成背景。")
            background, visual_engine = None, "复用已交付动态背景"
        elif s["kind"] == "video" and p.get("videoMotion") == "local":
            background, visual_engine = None, "本地商品运镜"
        elif s["kind"] == "video" and p.get("videoMotion") == "economy":
            from .video_api import economy_config, prepare_background
            cfg = economy_config()
            p["videoBackground"] = str(prepare_background(dest, p, cp, cfg=cfg))
            background, visual_engine = None, cfg["model"]
        elif s.get("regionEdit"):
            background, visual_engine = None, "海报局部修图"
        elif p.get("autoCreation") and s["kind"] != "copy" and p.get("bundleRole") not in ("white","overlay","box","bag","card"):
            background, visual_engine = None, "本地商品素材排版"
            if s["kind"] == "video" and model.route("video")["model"]:
                from .video_api import prepare_background
                p["videoBackground"] = str(prepare_background(dest, p, cp))
                visual_engine = p.get("videoModel") or model.route("video")["model"]
            else:
                background, visual_engine = make_scene(dest, p, ap, s["kind"], n == 1 or new_scene, strict=True, name=scene)
        elif p.get("bundleRole") or p.get("autoCreation"):
            background, visual_engine = None, "本地商品素材排版"
        else:
            background, visual_engine = make_scene(dest, p, ap, s["kind"], n == 1 or new_scene, name=scene)
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
                repair_plan = None
                if repair:
                    last_issues = visual["attempts"][-1]["issues"] if visual["attempts"] else []
                    last_review = visual.get("content")
                    repair_plan = classify_repair(
                        last_issues,
                        last_review,
                        has_generated_bg=bool(background and not s.get("regionEdit")),
                    )
                    visual["repairStrategy"] = repair_plan["strategy"]
                    if ap and p.get("bundleRole") != "overlay":
                        intact_mask = (
                            ap.name == "subject.png"
                            and not repair_plan["fallbackOriginal"]
                            and not any("抠图" in issue or "蒙版" in issue for issue in last_issues)
                        )
                        chosen = ap if intact_mask else original
                        design = p.get("design", {})
                        if (p.get("moment") and not p.get("layoutOverride")
                                and (not intact_mask or design.get("photoLayout") not in ("columns", "reply"))
                                and design.get("photoLayout") in ("columns", "reply", "object", "time", "clock-object")):
                            design["photoLayout"] = "bleed"
                            design["readingOrder"]["layoutReason"] = "首稿复检后使用满版摄影，给标题与实拍各留独立区域。"
                    if repair_plan["redrawBackground"] and s["kind"] == "poster":
                        stage(repair_plan["stage"])
                        if repair_plan.get("hint"):
                            vc = p.setdefault("promptBrief", {}).setdefault("visualConstraints", [])
                            if repair_plan["hint"] not in vc:
                                vc.append("修复上版画面问题：" + repair_plan["hint"])
                        try:
                            background, visual_engine = make_scene(
                                dest, p, chosen, s["kind"], True,
                                strict=bool(p.get("autoCreation")), name=f"{scene}-repair",
                            )
                            cp["visualEngine"] = visual_engine
                        except Exception:
                            pass
                visual.pop("content", None)
                try:
                    layout = None
                    if local_edit := s.get("regionEdit"):
                        source = DATA / t / "works" / local_edit["work"] / str(local_edit["version"])
                        layout = region_edit.original_layout(source, dest, cp)
                    if layout is None:
                        stage((repair_plan or {}).get("stage", "正在调整排版") if repair else
                              "正在合成逐镜口播、字幕与配乐" if p.get("productNarration") else "正在排版并导出成品")
                        film_context = {}
                        if locked_background:
                            film_context["backgroundArchive"] = str(dest.parent / str(locked_background) / "edit.zip")
                        if s.get("filmSourceVersion"):
                            source = dest.parent / str(s["filmSourceVersion"])
                            film_context["sourceEdit"] = str(source / "edit.zip")
                        if take := s.get("endingTake"):
                            film_context.update(previewFolder=str(DATA / t / "ending-previews" / take["task"] / take["batch"]),
                                                takeKey=take["key"])
                        layout = render(
                            dest,
                            {**p, "_filmRevision": film_context} if film_context else p,
                            cp,
                            s["kind"],
                            chosen,
                            s["ratio"],
                            s["variant"],
                            background,
                            custom_font,
                            repair=repair and not locked_background,
                        )
                    if s["kind"] == "poster":
                        region_edit.apply(dest,DATA / t / "works",layout,s,id)
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
                        stage("正在审核成品画面")
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
                    ) as exc:
                        # A damaged first export can also prevent preparing the model input.
                        review = (
                            None
                            if issues and not repair
                            else {
                                "status": "unavailable",
                                "reason": model.vision_failure_message(exc),
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
                if locked_background:
                    raise ValueError("背景对照未通过检查：" + "；".join(issues))
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
        if s["kind"] == "poster":
            # Map only text that appears in the delivered raster to a replaceable copy field.
            positions=[]
            for bounds, _, _, rendered in layout["frames"][0]["text"]:
                field=next((k for k in ("title","body","cta") if cp.get(k) and rendered.strip()==cp[k].strip()),None)
                if field:
                    positions.append(dict(field=field,box=[max(0,min(1,round(v/dims[i%2],5))) for i,v in enumerate(bounds)]))
            cp["editRegions"]=positions
            region_edit.save_layout(dest,layout)
            cp["protectedAreas"] = region_edit.protected(layout["frames"][0])
            if edit := s.pop("regionEdit",None):
                p.setdefault("backgroundPatches",[]).append(dict(work=work,version=n,job=id,box=edit["box"]))
        if p.get("merchantOffer"):
            from .merchant_offer import campaign_poster, check_delivery
            stage("正在核对活动海报、口播、字幕和发布配文" if s["kind"] == "video" else "正在核对发布配文的活动信息")
            offer = p["merchantOffer"]
            if s["kind"] == "video":
                campaign_poster(dest, ap.with_name("original.png"), offer)
            cp["merchantOfferProof"] = check_delivery(dest, p, s["kind"])
            checks.append({"label":"活动价核对", "detail":f"{offer['weekday']} {offer['amount']} 元 · " +
                           ("活动海报、发布配文、成片口播和两种字幕已分别读回。" if s["kind"] == "video" else "发布配文已读回。")})
        if renderer := layout.get("videoRenderer"):
            checks.append({"label": "短片渲染引擎", "detail": renderer})
        if visual:
            coverage = "已检查导出 PNG" + (
                f"及 MP4 全部 {24 * output.get('duration',9)} 帧，抽查各镜头首、中、尾帧"
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
            if layout.get("narration"):
                narration = layout["narration"]
                cp["narration"] = narration
                style = {"warm": "温暖亲切", "bright": "轻快明亮", "mixed": "分镜调节"}.get(narration.get("style"))
                voice = f'{narration["provider"]} · {narration["speaker"]}'
                if style and narration.get("styleApplied"):
                    voice += f" · {style}"
                checks.append({"label": "逐镜口播", "detail": f'{voice} · {len(narration["cues"])} 段同步字幕。'})
            checks.append(
                {
                    "label": "短片检查",
                    "detail": f"已核实 {dims[0]} × {dims[1]}、{output.get('duration',9)} 秒、24 fps 画面和声音轨道。",
                }
            )
        with db(True) as c:
            object_storage.enqueue(c,dest,["poster.png","offer-poster.png","copy.txt","poster.svg","video.mp4","edit.zip","open-design.zip","captions.srt"])
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
            if n == 1 and s["kind"] != "copy":
                growth.milestone(c,t,"generate",id)
            wallet.finish(c,t,id,True)
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
            wallet.finish(c,t,id,False)
            c.execute("UPDATE job SET state='failed',error=? WHERE id=?", (msg, id))


@app.get("/api/jobs/<id>")
def job_status(id):
    with db() as c:
        r = owner(c, "job", id, reqtenant())
    return jsonify({k: r[k] for k in ("id", "state", "work", "error", "version", "stage")})


@app.post("/api/jobs/<id>/retry")
def retry(id):
    t = reqtenant()
    with db(True) as c:
        j = owner(c, "job", id, t)
        if work_history.hidden(c, j["work"]):
            abort(404)
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
            wallet.reserve(c,t,id,j["cost"])
            spec = json.loads(j["spec"])
            if rid := spec["plan"].get("creationRun"):
                group = owner(c,"creative_run",rid,t)
                summary = json.loads(group["plan"])
                summary.pop("copyError",None)
                c.execute("UPDATE creative_run SET plan=? WHERE id=?",(dump(summary),rid))
            c.execute("UPDATE job SET state='queued',error=NULL,stage=NULL WHERE id=?", (id,))
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
        "offer-poster": "offer-poster.png",
        "post": "copy.txt",
        "design-source": "poster.svg",
        "edit-source": "edit.zip",
        "open-design-source": "open-design.zip",
        "subtitles": "captions.srt",
        "video": "video.mp4",
        "download": {"copy": "copy.txt", "poster": "poster.png", "video": "video.mp4"}[
            w["kind"]
        ],
    }.get(mode)
    path = DATA / t / "works" / id / str(n) / str(file)
    if not file:
        abort(404)
    suffix = "-OpenDesign.zip" if mode == "open-design-source" else path.suffix
    filename = "响指出片-" + json.loads(r["copy"])["title"] + suffix
    signed = None
    if mode in ("download","design-source","edit-source","open-design-source","subtitles") and request.headers.get("X-Trupic-Native") != "1":
        with db() as c:
            signed = object_storage.download_url(c,path,filename)
    if not signed and not path.exists():
        abort(404)
    if mode == "download":
        with db(True) as c:
            c.execute(
                "INSERT INTO downloads VALUES(?,?,1) ON CONFLICT(work,n) DO UPDATE SET count=count+1",
                (id, n),
            )
    if signed:
        from flask import redirect
        response = redirect(signed)
        response.headers["Cache-Control"] = "private, no-store"
        return response
    return send_file(
        path,
        as_attachment=mode in ("download", "design-source", "edit-source", "open-design-source", "subtitles"),
        download_name=filename,
        conditional=True,
    )


@app.route("/api/admin/pricing", methods=["GET", "POST"])
def admin_pricing():
    require_admin()
    actor = reqtenant()
    with db(request.method == "POST") as c:
        if request.method == "POST":
            pricing.update(c, actor, body())
        return jsonify(pricing.current(c))


@app.get("/api/admin")
def admin_state():
    require_admin()
    cfg = model.settings()
    with db() as c:
        group = None if is_admin(c) else staff.role(c)
        if group in ("finance","support"):
            return jsonify(allowedTabs=staff.TABS[group],role=group)
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
        dashboard = dict(
            metrics=dict(c.execute("""SELECT
                (SELECT COUNT(*) FROM merchant WHERE login IS NOT NULL AND date(created)=date('now')) registrations,
                (SELECT COUNT(DISTINCT tenant) FROM job WHERE date(created)=date('now')) active,
                (SELECT COUNT(DISTINCT tenant) FROM purchase WHERE state='paid') payers,
                (SELECT COALESCE(SUM(cents),0) FROM purchase WHERE state='paid') revenueCents,
                (SELECT COUNT(*) FROM job WHERE state='complete') delivered,
                (SELECT COUNT(*) FROM job WHERE state IN ('complete','failed')) finished,
                (SELECT COUNT(*) FROM merchant WHERE login IS NOT NULL AND date(created)=date('now','-7 days')) cohort,
                (SELECT COUNT(*) FROM merchant m WHERE login IS NOT NULL AND date(created)=date('now','-7 days') AND EXISTS
                    (SELECT 1 FROM job j WHERE j.tenant=m.id AND date(j.created)=date('now'))) retained""").fetchone()),
            costSummary=dict(c.execute("""SELECT (SELECT SUM(amount) FROM provider_bill WHERE currency='CNY') billed,
                (SELECT COUNT(*) FROM job_bill) reconciled,(SELECT COUNT(*) FROM cos_object WHERE error IS NOT NULL) storageErrors""").fetchone()),
            assistantMetrics={
                **personal_agent.metrics(c),
                "capabilities": personal_agent.planner.capability_registry(c),
            },
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
            modelFailures=[
                dict(r)
                for r in c.execute(
                    """SELECT platform,model,kind,error,COUNT(*) calls FROM model_call
                    WHERE day=? AND ok=0 GROUP BY platform,model,kind,error ORDER BY calls DESC""",
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
                "engine": model.engine_name() or "未启用文字模型",
            },
            skills=skill_library_catalog(c),
            viewer=session.get("tenant"),
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
                    "SELECT a.action,a.target,a.created,a.actor,m.login FROM audit a LEFT JOIN merchant m ON m.id=a.actor ORDER BY a.id DESC LIMIT 80"
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

        if group:
            keys = ("works","visualReviews","cases","events","eventFeeds","jobs","effects")
            return jsonify(**{k:dashboard[k] for k in keys},allowedTabs=staff.TABS[group],role=group)
        return jsonify(dashboard)


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
    if action == "skill-import":
        with db(True) as c:
            import_package(c, t, v)
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
            if action == "model-routes":
                providers.select(c, t, v)
            else:
                activate = v.get("activate") is True and v.get("capability") in providers.KINDS
                before = providers.route_snapshot(c) if activate else None
                providers.save(c, t, v)
                if activate:
                    providers.select(c, t, {v["capability"]: v["id"],
                                            "expectedVersion": v.get("expectedVersion")}, before=before)
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
        validate_pinterest_settings(cfg)
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
        validate_pinterest_settings(cfg)
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


costs.register(app, globals())
reference_assets.register(app, globals())
staff.register(app, globals())
growth.register(app, globals())
commerce.register(app, globals())
coupons.register(app, globals())
work_history.register(app, globals())
register_bundles(app, globals())
creation_submit, creation_details = register_creations(app, globals())
personal_agent.register(app, globals())
merchant_blind.register(app, globals())
register_voice(app, reqtenant)
register_model_tools(app, globals())
model_admission.register(app, globals())


def start():
    # Nothing can still be running on a host where this process is the only producer.
    with db(True) as c:
        for j in c.execute(
            "SELECT id,worker_pid,created FROM job WHERE state='running'"
        ).fetchall():
            if not worker_alive(j["worker_pid"], j["created"]):
                c.execute("UPDATE job SET state='queued',stage=NULL WHERE id=?", (j["id"],))
        pending = [
            row[0] for row in c.execute("SELECT id FROM job WHERE state='queued'")
        ]
    for id in pending:
        pool.submit(produce, id)

    if object_storage.destination():
        def mirror_files():
            while True:
                try:
                    idle = not object_storage.drain()
                except Exception:
                    # A busy database must not stop the mirror for the rest of the process lifetime.
                    app.logger.exception("Storage mirror interrupted")
                    idle = True
                if idle:
                    time.sleep(5)
        threading.Thread(target=mirror_files,daemon=True,name="cos-mirror").start()

    def sync():
        last_sync = 0
        last_week = None
        while True:
            try:
                event_sources.refresh_due()
                recover_jobs()
                with db(True) as c:
                    commerce.close_stale(c)
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
            except Exception:
                # One failed tick must not end weekly topics, event sync or job recovery.
                app.logger.exception("Scheduled work interrupted")
            time.sleep(60)

    threading.Thread(target=sync, daemon=True).start()
    from waitress import serve

    port = int(os.getenv("PORT", 7341))
    print(f"响指出片 Trupic  http://127.0.0.1:{port}", flush=True)
    serve(app, host=os.getenv("TRUPIC_HOST", "127.0.0.1"), port=port, threads=8)


if __name__ == "__main__":
    start()
