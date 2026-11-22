"""One request, a shared creative brief, and independently recoverable deliveries."""
import copy
import json
import re
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

from flask import abort, jsonify, send_file
from itsdangerous import BadSignature

from .campaign import LOCKED, storyboard
from .creative import draft_copy
from .design import visual_requests
from .formats import output_spec
from .product_bundle import qualified_cutout
from .prompt_agent import optimize
from .skill_library import attach
from .store import DATA, db, dump, ident, now

LABELS = {"copy": "推广文案", "poster": "营销海报", "hero": "商品主图", "benefit": "卖点图", "scene": "场景图", "white": "白底图", "cover": "小红书封面", "detail": "卖点展开页", "closing": "收尾页", "campaign": "活动海报", "price": "价格图", "banner": "活动横幅", "announcement": "直播预告", "livecover": "直播封面", "livebackground": "直播背景", "overlay": "透明贴片", "motion": "九秒商品短片", "box": "包装盒样机", "bag": "手提袋样机", "card": "品牌卡样机"}


def route_request(brief):
    positive = visual_requests(brief).lower()
    # Reserved capabilities never silently become a generic, billed poster.
    if re.search(r"详情页|建站|网站|网页|app\s*界面|角色设定|三视图|多角度|视频重制", positive):
        return {"unsupported": "这项需求需要额外素材或尚未接入的制作能力。可以先描述要做的海报、上新组图或九秒商品短片。"}
    only_copy = bool(re.search(r"(?:只|仅).{0,5}(?:文案|文字)", positive))
    video = bool(re.search(r"视频|短片|短视频|动态海报", positive)) and not only_copy
    image_words = bool(re.search(r"海报|主图|卖点图|场景图|白底图|图片|组图|上新|上架|新品|封面|横幅|素材包", positive))
    pictures = not only_copy and (not video or image_words)
    if not image_words and re.search(r"(?:只|仅).{0,5}(?:视频|短片)", positive):
        pictures = False
    if re.search(r"文案|推广语", positive) and not image_words and not video:
        pictures = False
    single = bool(re.search(r"一张|单张|(?:只|仅).{0,5}(?:海报|封面)", positive))
    workflow, roles = None, []
    if pictures:
        if "样机" in positive:
            workflow, roles = "mockup", ["box", "bag", "card"]
        elif "直播" in positive:
            workflow, roles = "live", ["announcement", "livecover", "livebackground", "overlay"]
        elif re.search(r"促销|优惠|折扣|满减", positive):
            workflow, roles = "promotion", ["campaign"] if single else ["campaign", "price", "banner"]
        elif "小红书" in positive:
            workflow, roles = "social", ["cover"] if single else ["cover", "detail", "closing"]
        elif not single and re.search(r"上新|上架|新品|素材包|一套", positive):
            workflow, roles = "launch", ["hero", "benefit", "scene"]
        elif any(word in positive for word in ("主图", "卖点图", "场景图", "白底图")):
            workflow = "launch"
            roles = [role for word, role in (("主图", "hero"), ("卖点图", "benefit"), ("场景图", "scene"), ("白底图", "white")) if word in positive]
        elif "横幅" in positive or "banner" in positive:
            roles = ["banner"]
        else:
            roles = ["poster"]
    if video:
        roles.append("motion")
    return dict(workflow=workflow, roles=["copy", *roles])


def factual_lines(brief, extra, profile):
    """Keep user-provided product facts, excluding requests and sample instructions."""
    values = []
    for text in (profile.get("facts", ""), extra, brief):
        for clause in re.split(r"[。；;\n，,]", text):
            clause = clause.strip(" ·")
            if not clause or LOCKED.search(clause):
                continue
            if re.search(r"不要|别写|禁止|不提|假设|例如|比如|参考价|未确认|待定", clause):
                continue
            if re.search(r"(?:做|制作|生成|帮我|设计|需要|来一|输出|配一).*(?:海报|视频|短片|组图|文案|素材|封面)", clause):
                continue
            if re.search(r"(?:秒|[:：]\d+|像素|分辨率|画幅).*(?:短片|视频|海报|组图)|^(?:横版|竖屏|方形|\d+[:：]\d+)$", clause):
                continue
            if re.search(r"\d|搭配|材质|配料|成分|可拆|冲调|尺寸|规格|开播|仅限|不与|售后|保修|口味|适用|不限|全店|全场|同享|不叠加|无其他限制|今天|明天|本周|周末|长期|买.{1,4}送", clause):
                values.append(clause)
    return list(dict.fromkeys(values))


def coordinate(services, c, tenant, v):
    brief, extra = services["string"](v.get("brief"), 1200), services["string"](v.get("facts"), 400)
    if len(brief) < 2:
        raise ValueError("请用一句话描述想推广什么、希望得到什么。")
    route = route_request(brief)
    if route.get("unsupported"):
        return dict(ready=False, message=route["unsupported"], questions=[])
    if not v.get("asset"):
        return dict(ready=False, message="先上传一张商品图。", questions=[])
    asset_row = services["owner"](c, "asset", v["asset"], tenant)
    asset = json.loads(asset_row["info"])
    if asset["risk"]:
        return dict(ready=False, message="这张图片清晰度不足，请换一张能看清商品的照片。", questions=[])
    profile = json.loads(c.execute("SELECT profile FROM merchant WHERE id=?", (tenant,)).fetchone()[0])
    lines = factual_lines(brief, extra, profile)
    facts = "；".join(lines)
    questions = []
    if route["workflow"] == "promotion":
        if not re.search(r"\d+(?:\.\d+)?\s*(?:元|折)|[￥¥]\s*\d|买.{1,4}送|满.{1,6}减", facts):
            questions.append("请补充实际价格或优惠内容。")
        if not re.search(r"\d+月\d+日|\d{4}[-/]\d|周[一二三四五六日末]|今天|明天|本周|长期", facts):
            questions.append("请补充活动有效期。")
        if not re.search(r"仅限|适用|不限|全店|全场|不与|同享|不叠加|无其他限制", facts):
            questions.append("请补充适用条件，没有额外限制也可说明。")
    if route["workflow"] == "live" and not re.search(r"\d{1,2}[:：]\d{2}|\d{1,2}点", facts):
        questions.append("请补充直播日期、开播时间与直播内容。")
    if questions:
        return dict(ready=False, message="补充这些信息后，就可以开始制作。", questions=questions)
    kit_row = c.execute("SELECT value FROM brand_kit WHERE tenant=?", (tenant,)).fetchone()
    kit = json.loads(kit_row[0]) if kit_row else {}
    if kit.get("logo"):
        services["owner"](c, "asset", kit["logo"], tenant)
    # Full original is always safe to use. Only supplied transparency is eligible
    # for automatic cutout use; machine-extracted masks still need human review.
    asset["path"] = DATA / tenant / "assets" / v["asset"] / "subject.png"
    cutout = bool(asset.get("suppliedTransparency")) and qualified_cutout(asset, True)
    roles = list(route["roles"])
    if "white" in roles and not cutout:
        return dict(ready=False, message="制作白底图需要合格的透明底商品图，请更换图片；也可以先制作主图、卖点图或海报。", questions=[])
    if route["workflow"] == "launch" and cutout and all(role in roles for role in ("hero", "benefit", "scene")) and "white" not in roles:
        roles.insert(roles.index("scene") + 1, "white")
    common_request = dict(brief=brief, facts=facts, kind="poster", asset=v["asset"], assetMode="cutout" if cutout else "original", assetConfirmed=True, ratio="portrait", resolution=1080, lettering="off", fontId=kit.get("font") or "profile")
    if services["FIDELITY"].search(brief):
        common_request["identityRegion"] = [0, 0, 1, 1]
    base = services["plan_spec"](c, tenant, common_request)
    if kit.get("name"):
        base["plan"]["profile"]["name"] = kit["name"]
    # Local creative director writes one brief; the text and visual stages share it.
    optimize(base, infer=False)
    product = base["plan"]["promptBrief"]["reading"]["product"]
    locked = LOCKED.search(brief)
    cp = draft_copy(base["plan"])
    cp["title"] = locked.group(1) if locked else cp["title"]
    if not locked and "抹茶" in brief + product and "牛奶" in facts:
        cp["title"] = "给牛奶加一点" + (kit.get("name") or profile.get("name") or "抹茶")
    cp["body"] = "；".join(lines) if lines else product + "，看看商品的细节。"
    cp["cta"] = "查看商品规格" if not re.search(r"不要行动|不需要行动|不加引导", brief) else ""
    cp["detailLine"] = cp["body"]
    cp["terms"] = "；".join(line for line in lines if re.search(r"仅限|适用|不与|同享|不叠加|月\d+日|周末|长期", line)) if route["workflow"] == "promotion" else ""
    cp["offer"] = ""
    price = re.search(r"[¥￥]?\d+(?:\.\d+)?元(?:[/／][^，。；\s·]+)?", facts)
    if price:
        cp["offer"] = price.group()
    cp["review"] = "文案、画面与分镜共用本次商品资料；原图像素和成品文字在导出后复检。"
    shared_id = ident()
    common = dict(id=shared_id, product=product, request=brief, facts=lines, title=cp["title"], body=cp["body"], cta=cp["cta"], terms=cp["terms"], offer=cp["offer"], concept=base["plan"].get("posterArt",{}).get("concept",""), sourceAsset=v["asset"], brand=kit, roles=roles)
    specs=[]
    for role in roles:
        spec=copy.deepcopy(base)
        kind="copy" if role=="copy" else "video" if role=="motion" else "poster"
        spec["kind"]=kind
        ratio="story" if kind=="video" or route["workflow"]=="live" else "landscape" if role=="banner" else "square" if route["workflow"] in ("launch","mockup") else "portrait"
        positive=visual_requests(brief)
        for pattern, requested in ((r"1[:：]1|方形", "square"),(r"3[:：]4", "portrait"),(r"9[:：]16|竖屏", "story"),(r"16[:：]9|横版", "landscape")):
            if re.search(pattern,positive): ratio=requested
        spec["ratio"]=ratio
        p=spec["plan"]
        p.update(kind=kind,autoCreation=True,coordination=common,brandKit=kit)
        p["output"]=output_spec(kind,ratio,720 if kind=="video" else 1080)
        attach(p,kind,workflow=route["workflow"])
        # Recompile the visual brief for each output, retaining the shared facts
        # and exact copy. No model/API calls are needed for this path.
        optimize(spec,infer=False)
        if role not in ("copy","poster"):
            p["bundleRole"]=role
        spec["replacement"]=copy.deepcopy(cp)
        if role in ("scene","white","livebackground","box","bag","card"):
            spec["replacement"]["title"]=""
        if role=="price" and price:
            spec["replacement"]["title"]=price.group()
        if role=="closing":
            spec["replacement"]["title"]=cp["cta"] or product
        if role=="motion":
            spec["replacement"]["storyboard"]=storyboard(p,spec["replacement"])
        specs.append(dict(role=role,label=LABELS[role],spec=spec))
    from . import model
    notes = ["商品与文字保留原图及已确认资料。"]
    if model.route("text")["model"]:
        notes.append("文案由后台所选模型制作，并统一用于图片和短片。")
    if "motion" in roles:
        notes.append("视频使用所选视频接口生成动态环境，再合成商品、字幕与配乐。" if model.route("video")["model"] else "视频使用九秒三镜的本地镜头运动。")
    return dict(ready=True,title=cp["title"],brief=brief,shared=common,items=specs,cost=sum(services["COST"][row["spec"]["kind"]] for row in specs),notes=notes)


def register(app, services):
    owner, tenant, quotes = services["owner"], services["reqtenant"], services["quotes"]
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS creative_run(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,request_key TEXT NOT NULL,title TEXT NOT NULL,brief TEXT NOT NULL,plan TEXT NOT NULL,items TEXT NOT NULL,created TEXT NOT NULL,UNIQUE(tenant,request_key))")

    def details(c,row):
        items=[]
        for item in json.loads(row["items"]):
            job=owner(c,"job",item["job"],row["tenant"])
            spec=json.loads(job["spec"])
            base=f"/api/works/{job['work']}/v/{job['version']}"
            done=job["state"]=="complete"
            cp=json.loads(job["copy_checkpoint"]) if job["copy_checkpoint"] else spec["replacement"]
            items.append({**item,"kind":spec["kind"],"state":job["state"],"error":job["error"],"work":job["work"],"preview":base+"/poster" if done and spec["kind"]!="copy" else None,"video":base+"/video" if done and spec["kind"]=="video" else None,"text":"\n\n".join(cp[k] for k in ("title","body","cta") if cp.get(k)) if done and spec["kind"]=="copy" else None,"download":base+"/download" if done else None})
        complete=all(i["state"]=="complete" for i in items)
        return dict(id=row["id"],requestKey=row["request_key"],title=row["title"],brief=row["brief"],created=row["created"],items=items,complete=complete,active=any(i["state"] in ("queued","running") for i in items),download=f"/api/creations/{row['id']}/download",summary=json.loads(row["plan"]))

    @app.post("/api/creations/plan")
    def auto_preview():
        t=tenant()
        with db() as c:
            result=coordinate(services,c,t,services["body"]())
        if not result["ready"]:
            return jsonify(result)
        return jsonify(ready=True,title=result["title"],cost=result["cost"],deliveries=[dict(label=i["label"],kind=i["spec"]["kind"]) for i in result["items"]],notes=result["notes"],quote=quotes.dumps({"autoCreation":True,"tenant":t,**result}))

    @app.post("/api/creations")
    def auto_create():
        t,v=tenant(),services["body"]()
        key=services["string"](v.get("requestKey"),90)
        if not key: raise ValueError("缺少请求标识，请刷新后重试。")
        ids=[]
        with db(True) as c:
            old=c.execute("SELECT * FROM creative_run WHERE tenant=? AND request_key=?",(t,key)).fetchone()
            if old: return jsonify(details(c,old))
            try: q=quotes.loads(v.get("quote",""),max_age=1800)
            except BadSignature: raise ValueError("方案已过期，请稍后重新开始创作。")
            if not q.get("autoCreation") or q["tenant"]!=t: abort(403)
            if v.get("confirmedCost")!=q["cost"]: raise ValueError("创作费用已更新，请查看按钮旁的积分后重试。")
            services["enough"](c,t,q["cost"])
            rid=ident(); items=[]
            for entry in q["items"]:
                spec=entry["spec"]
                spec["plan"]["creationRun"]=rid
                owner(c,"asset",spec["asset"],t)
                jid,wid=ident(),ident()
                c.execute("INSERT INTO job(id,tenant,request_key,spec,state,cost,work,version,error,created)VALUES(?,?,?,?,?,?,?,?,?,?)",(jid,t,f"auto:{rid}:{entry['role']}",dump(spec),"queued",services["COST"][spec["kind"]],wid,1,None,now()))
                items.append(dict(job=jid,role=entry["role"],label=entry["label"]))
                ids.append(jid)
            summary=dict(product=q["shared"]["product"],facts=q["shared"]["facts"],cost=q["cost"],notes=q["notes"])
            c.execute("INSERT INTO creative_run VALUES(?,?,?,?,?,?,?,?)",(rid,t,key,q["title"],q["brief"],dump(summary),dump(items),now()))
            result=details(c,owner(c,"creative_run",rid,t))
        for jid in ids: services["pool"].submit(services["produce"],jid)
        return jsonify(result)

    @app.get("/api/creations")
    def auto_listing():
        t=tenant()
        with db() as c:
            return jsonify([details(c,row) for row in c.execute("SELECT * FROM creative_run WHERE tenant=? ORDER BY created DESC,rowid DESC LIMIT 30",(t,)).fetchall()])

    @app.get("/api/creations/<id>")
    def auto_detail(id):
        with db() as c: return jsonify(details(c,owner(c,"creative_run",id,tenant())))

    @app.get("/api/creations/<id>/download")
    def auto_download(id):
        t=tenant(); stream=BytesIO()
        with db() as c:
            row=owner(c,"creative_run",id,t); result=details(c,row)
            if not result["complete"]: raise ValueError("请等待全部成品完成，失败项可以单独重试。")
            with ZipFile(stream,"w",ZIP_DEFLATED) as archive:
                for n,item in enumerate(result["items"],1):
                    job=owner(c,"job",item["job"],t)
                    folder=DATA/t/"works"/job["work"]/str(job["version"])
                    name={"copy":"copy.txt","poster":"poster.png","video":"video.mp4"}[item["kind"]]
                    path=folder/name
                    if not path.is_file(): raise ValueError("成品文件缺失，请联系管理员恢复。")
                    archive.write(path,f"{n:02d}-{item['label']}{path.suffix}")
                    for optional in ("edit.zip","open-design.zip") if item["kind"]=="video" else ():
                        if (folder/optional).is_file(): archive.write(folder/optional,f"{n:02d}-{item['label']}-{optional}")
        stream.seek(0)
        return send_file(stream,mimetype="application/zip",as_attachment=True,download_name="创作成品.zip")
