"""Product launch packs with independently recoverable, existing poster jobs."""

import copy
import json
import re
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

from flask import jsonify, send_file, abort
from itsdangerous import BadSignature
from PIL import Image

from . import pricing, work_history, wallet
from .store import db, DATA, ident, now, dump
from .skill_catalog import SKILLS, ROLE_NAMES, VIDEO_ROLES
from .copy_choices import selected_copy, apply_choice
from .formats import output_spec
from .skill_library import attach as attach_skills, effective_versions

ROLES = {"hero": "主图", "benefit": "卖点图", "scene": "场景图", "white": "白底图"}


def qualified_cutout(asset, confirmed):
    if not confirmed or asset["risk"] or asset["file"] != "subject.png":
        return False
    path = asset["path"]
    if not path.is_file():
        return False
    with Image.open(path) as im:
        alpha = im.convert("RGBA").getchannel("A")
        hist = alpha.histogram()
        coverage = sum(hist[128:]) / (im.width * im.height)
        # Use the same foreground threshold as the coverage measurement. A soft
        # antialiased fringe reaching the edge does not clip the opaque product.
        box = alpha.point(lambda value: 255 if value >= 128 else 0).getbbox()
        return bool(
            box
            and min(im.size) >= 220
            and 0.05 < coverage < 0.9
            and box[0] > 0
            and box[1] > 0
            and box[2] < im.width
            and box[3] < im.height
        )


def register(app, services):
    owner, tenant = services["owner"], services["reqtenant"]
    quotes, pool = services["quotes"], services["pool"]
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS brand_kit(tenant TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS product_bundle(
            id TEXT PRIMARY KEY, tenant TEXT NOT NULL, request_key TEXT NOT NULL,
            title TEXT NOT NULL, items TEXT NOT NULL, created TEXT NOT NULL,
            UNIQUE(tenant, request_key));
        """)

    @app.get("/api/creative-skills")
    def catalog():
        return jsonify([dict(id=key, **value) for key, value in SKILLS.items()])

    @app.route("/api/brand-kit", methods=["GET", "POST"])
    def brand_kit():
        from flask import request

        t = tenant()
        with db(True) as c:
            if request.method == "POST":
                v = services["body"]()
                kit = {
                    k: services["string"](v.get(k), 100)
                    for k in ("name", "logo", "color", "font")
                }
                if not kit["name"] or not re.fullmatch(
                    r"#[0-9a-fA-F]{6}", kit["color"]
                ):
                    raise ValueError("请填写品牌名称和有效的品牌色。")
                if kit["logo"]:
                    owner(c, "asset", kit["logo"], t)
                if kit["font"]:
                    font = owner(c, "brand_font", kit["font"], t)
                    kit["fontName"] = json.loads(font["info"])["name"]
                c.execute(
                    "INSERT INTO brand_kit VALUES(?,?) ON CONFLICT(tenant) DO UPDATE SET value=excluded.value",
                    (t, dump(kit)),
                )
            row = c.execute(
                "SELECT value FROM brand_kit WHERE tenant=?", (t,)
            ).fetchone()
            return jsonify(
                json.loads(row[0])
                if row
                else dict(name="", logo="", color="#315744", font="")
            )

    def details(c, row):
        items = []
        skill = "launch"
        for item in json.loads(row["items"]):
            job = owner(c, "job", item["job"], row["tenant"])
            skill = json.loads(job["spec"])["plan"].get("bundleSkill", "launch")
            if work_history.hidden(c, job["work"]):
                continue
            base = f"/api/works/{job['work']}/v/{job['version']}"
            items.append(
                {
                    **item,
                    "state": job["state"],
                    "kind": json.loads(job["spec"])["kind"],
                    "video": base + "/video"
                    if job["state"] == "complete"
                    and json.loads(job["spec"])["kind"] == "video"
                    else None,
                    "error": job["error"],
                    "preview": base + "/poster" if job["state"] == "complete" else None,
                    "download": base + "/download"
                    if job["state"] == "complete"
                    else None,
                }
            )
        return dict(
            id=row["id"],
            title=row["title"],
            skill=skill,
            skillName=SKILLS[skill]["name"],
            items=items,
            complete=bool(items) and all(i["state"] == "complete" for i in items),
            download=f"/api/bundles/{row['id']}/download",
        )

    @app.post("/api/bundles/preview")
    def bundle_preview():
        t, v = tenant(), services["body"]()
        skill = v.get("skill", "launch")
        if skill not in SKILLS:
            raise ValueError("请选择有效的创作技能。")
        title = services["string"](v.get("title"), 60)
        benefits = services["string"](v.get("benefits"), 200)
        if not title or not benefits or not v.get("asset"):
            raise ValueError("请填写商品名称、已确认卖点，并选择商品照片。")
        with db() as c:
            rates = pricing.current(c)
            kit_row = c.execute(
                "SELECT value FROM brand_kit WHERE tenant=?", (t,)
            ).fetchone()
            kit = json.loads(kit_row[0]) if kit_row else {}
            if kit.get("logo"):
                owner(c, "asset", kit["logo"], t)
            if skill == "brand" and not kit.get("name"):
                raise ValueError("请先保存品牌规范。")
            s = services["plan_spec"](
                c,
                t,
                {
                    **v,
                    "kind": "poster",
                    "brief": title + "。" + benefits,
                    "facts": benefits,
                    "lettering": "off",
                    "fontId": kit.get("font") or "profile",
                },
            )
            overrides = effective_versions(c, t)
            asset = json.loads(owner(c, "asset", s["asset"], t)["info"])
        asset["path"] = DATA / t / "assets" / s["asset"] / "subject.png"
        white = qualified_cutout(asset, v.get("assetConfirmed") is True)
        roles = list(SKILLS[skill]["roles"])
        if skill == "launch" and white:
            roles.append("white")
        if skill == "angles" and (not v.get("sideAsset") or not v.get("backAsset")):
            raise ValueError("请提供同一商品的正面、侧面与背面实拍。")
        if skill == "promotion" and not services["string"](v.get("terms"), 150):
            raise ValueError("请填写活动有效期及适用条件。")
        template = None
        if skill == "remake":
            with db() as c:
                work = owner(c, "work", v.get("template"), t)
                if work["kind"] != "video":
                    raise ValueError("请选择已有的九秒短片。")
                template = json.loads(
                    c.execute(
                        "SELECT spec FROM version WHERE work=? AND n=?",
                        (work["id"], work["current"]),
                    ).fetchone()[0]
                )
        specs = []
        for role in roles:
            spec = copy.deepcopy(s)
            if role in ("side", "back"):
                spec["asset"] = v["sideAsset" if role == "side" else "backAsset"]
                with db() as c:
                    info = json.loads(owner(c, "asset", spec["asset"], t)["info"])
                if info["risk"]:
                    raise ValueError("多角度照片中有图片清晰度不足。")
            if template:
                spec["ratio"] = template["ratio"]
                spec["plan"]["design"] = copy.deepcopy(
                    template["plan"].get("design", spec["plan"]["design"])
                )
            spec["kind"] = "video" if role in VIDEO_ROLES else "poster"
            spec["ratio"] = (
                "landscape" if role in ("banner", "brandbanner") else spec["ratio"]
            )
            if skill in ("live", "social"):
                spec["ratio"] = "story" if skill == "live" else "portrait"
            spec["plan"]["kind"] = spec["kind"]
            spec["plan"]["output"] = output_spec(
                spec["kind"],
                spec["ratio"],
                720 if role in VIDEO_ROLES else v.get("resolution", 1080),
                v.get("dpi", 300),
            )
            spec["plan"]["brandKit"] = kit
            spec["plan"]["bundleSkill"] = skill
            if kit.get("name"):
                spec["plan"]["profile"]["name"] = kit["name"]
            spec["plan"]["original"] += " " + services["string"](v.get("terms"), 150)
            spec["plan"]["facts"] += " " + services["string"](v.get("terms"), 150)
            if skill == "angles":
                with db() as c:
                    angle_asset = json.loads(
                        owner(c, "asset", spec["asset"], t)["info"]
                    )
                angle_asset["path"] = (
                    DATA / t / "assets" / spec["asset"] / "subject.png"
                )
                spec["assetMode"] = (
                    "cutout" if qualified_cutout(angle_asset, True) else "original"
                )
            else:
                spec["assetMode"] = "cutout" if white else "original"
            spec["plan"]["bundleRole"] = role
            spec["plan"]["promptBrief"] = {"source": "商品上新素材包"}
            spec["replacement"] = dict(
                title=title
                if role
                not in (
                    "scene",
                    "white",
                    "livebackground",
                    "front",
                    "side",
                    "back",
                    "box",
                    "bag",
                    "card",
                )
                else "",
                body=benefits,
                cta="",
                offer="",
                terms=services["string"](v.get("terms"), 150)
                if skill == "promotion"
                else "",
                review="使用商家确认的商品名与卖点。",
            )
            if role == "guideline":
                spec["replacement"]["body"] = (
                    f"品牌 {kit['name']}\n品牌色 {kit['color']}\n字体 {kit.get('fontName') or '思源黑体 / 思源宋体'}"
                )
            if role == "closing":
                spec["replacement"]["title"] = (
                    services["string"](v.get("cta"), 60) or "选购信息"
                )
            if role == "announcement":
                spec["replacement"]["title"] = "直播预告 · " + title
            if role == "price":
                price = re.search(
                    r"[¥￥]?\d+(?:\.\d+)?元(?:[/／][^，。\s]+)?", benefits
                )
                spec["replacement"]["title"] = price.group() if price else title
            if role == "campaign":
                spec["replacement"]["title"] = "限时活动 · " + title
            if role in VIDEO_ROLES:
                spec["replacement"]["cta"] = (
                    services["string"](v.get("cta"), 60) or "查看商品规格"
                )
                price = re.search(
                    r"[¥￥]?\d+(?:\.\d+)?元(?:[/／][^，。\s·]+)?", benefits
                )
                spec["replacement"]["offer"] = price.group() if price else ""
            attach_skills(spec["plan"], spec["kind"], workflow=skill, overrides=overrides)
            specs.append(spec)
        note = SKILLS[skill]["description"]
        if skill == "launch":
            note = (
                "已加入白底图"
                if white
                else "白底图需边缘完整、通过检查并已确认的透明抠图。当前交付三张，场景图保留原照片环境。"
            )
        cost = sum(pricing.snapshot(spec, rates) for spec in specs)
        return jsonify(
            title=title,
            roles=[ROLE_NAMES[r] for r in roles],
            requiresCopyChoice=any(s["kind"] == "poster" for s in specs),
            cost=cost,
            note=note,
            quote=quotes.dumps(
                dict(bundle=True, tenant=t, title=title, specs=specs, cost=cost)
            ),
        )

    @app.post("/api/bundles")
    def create_bundle():
        t, v = tenant(), services["body"]()
        key = services["string"](v.get("requestKey"), 90)
        if not key:
            raise ValueError("缺少请求标识，请刷新后重试。")
        ids = []
        with db(True) as c:
            old = c.execute(
                "SELECT * FROM product_bundle WHERE tenant=? AND request_key=?",
                (t, key),
            ).fetchone()
            if old:
                return jsonify(details(c, old))
            try:
                q = quotes.loads(v.get("quote", ""), max_age=1800)
            except BadSignature:
                raise ValueError("方案已过期，请重新确认。")
            if not q.get("bundle") or q["tenant"] != t:
                abort(403)
            if v.get("confirmed") is not True or v.get("confirmedCost") != q["cost"]:
                raise ValueError("请确认整套素材的积分用量。")
            if any(s["kind"] == "poster" for s in q["specs"]):
                chosen = selected_copy(quotes, v)
                for spec in q["specs"]:
                    apply_choice(spec, chosen)
            services["enough"](c, t, q["cost"])
            bid, items = ident(), []
            for spec in q["specs"]:
                owner(c, "asset", spec["asset"], t)
                jid, wid = ident(), ident()
                role = spec["plan"]["bundleRole"]
                c.execute(
                    "INSERT INTO job(id,tenant,request_key,spec,state,cost,work,version,error,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        jid,
                        t,
                        f"bundle:{bid}:{role}",
                        dump(spec),
                        "queued",
                        pricing.quoted_cost(spec),
                        wid,
                        1,
                        None,
                        now(),
                    ),
                )
                wallet.reserve(c,t,jid,pricing.quoted_cost(spec))
                ids.append(jid)
                items.append(dict(role=role, label=ROLE_NAMES[role], job=jid))
            c.execute(
                "INSERT INTO product_bundle VALUES(?,?,?,?,?,?)",
                (bid, t, key, q["title"], dump(items), now()),
            )
            result = details(c, owner(c, "product_bundle", bid, t))
        for jid in ids:
            pool.submit(services["produce"], jid)
        return jsonify(result)

    @app.get("/api/bundles")
    def list_bundles():
        t = tenant()
        with db() as c:
            return jsonify(
                [
                    entry
                    for r in c.execute(
                        "SELECT * FROM product_bundle WHERE tenant=? ORDER BY created DESC,rowid DESC",
                        (t,),
                    ).fetchall() if (entry := details(c, r))["items"]
                ]
            )

    @app.get("/api/bundles/<id>")
    def get_bundle(id):
        with db() as c:
            return jsonify(details(c, owner(c, "product_bundle", id, tenant())))

    @app.get("/api/bundles/<id>/download")
    def download_bundle(id):
        t = tenant()
        with db() as c:
            pack = details(c, owner(c, "product_bundle", id, t))
            if not pack["complete"]:
                raise ValueError("请等待全部图片完成后下载。失败图片可以单独重试。")
            stream = BytesIO()
            with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
                for i, item in enumerate(pack["items"], 1):
                    j = owner(c, "job", item["job"], t)
                    path = (
                        DATA
                        / t
                        / "works"
                        / j["work"]
                        / str(j["version"])
                        / ("video.mp4" if item["kind"] == "video" else "poster.png")
                    )
                    if not path.is_file():
                        raise ValueError("成品文件缺失，请联系管理员恢复文件。")
                    archive.write(path, f"{i:02d}-{item['label']}{path.suffix}")
                    if item["kind"] == "video":
                        for name in ("edit.zip", "open-design.zip"):
                            source = path.parent / name
                            if source.is_file():
                                archive.write(source, f"{i:02d}-{item['label']}-{name}")
        stream.seek(0)
        return send_file(
            stream,
            mimetype="application/zip",
            as_attachment=True,
            download_name="创作素材包.zip",
        )


# Kept here for the existing renderer entry point.
from .skill_render import render_product
