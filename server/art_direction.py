"""Product-specific art direction adapted from hiccai-poster, revision 46994ee."""

import re
from .design import requested_style, visual_requests

REVISION = "46994ee264893a0d22608b78cda2333bcfbb6ce2"


def direct(plan, style, product, focus):
    profile = plan["profile"]
    facts = "。".join(filter(None, (plan.get("facts"), profile.get("facts"))))
    context = " ".join((plan["original"], profile.get("product", ""), product))
    optics = bool(
        re.search(r"相机|单反|微单|摄影器材|镜头卡口|camera body", context, re.I)
    )
    methods = ["hiccai-poster"]
    source = plan.get("visualSource")
    brief = plan["original"]
    # A negative request must not activate the very treatment it excludes.
    positive = visual_requests(brief)
    type_requested = plan.get("lettering") in ("both", "han", "latin") or bool(
        re.search("字形穿插|字图穿插|食材大字|型号大字|放大.{0,3}(型号|食材字)", positive)
    )
    reference = ""
    composition = "studio"
    mark = ""
    print_palette = None
    story = ""
    orchard = False
    lighting = ""
    if style == "food-motion":
        composition = style
        lighting = "dark" if re.search("暗调|暗底|黑底|逆光|居酒屋|深色|夜食", positive) else "bright"
        mechanism = "暗调聚光" if lighting == "dark" else "明快食材主视觉"
        feature, detail = "食材表面与原片动作", ""
        concept = (
            "让照片里可见的筷子、餐具或食材形状决定方向，原菜品是第一视觉。"
            + ("以集中暖侧光衬托食材纹理，标题落在暗部外缘。" if lighting == "dark" else "用一块明亮色面托住食材，标题对准留白边缘。")
            + "价格和适用条件放在同一阅读区。"
        )
        reference = "本地 02 用筷子和碎屑制造方向，Pinterest 美食参考用挑起的面条组织负空间。"
    elif style == "quiet-light":
        composition = style
        mechanism, feature, detail = "单物侧光与留白", "实物表面与受光边缘", ""
        concept = "缩小实物在画面的占比，让连续留白扩大比例落差。光聚在实物附近，标题与细字留在安静色面，保持物件边缘和包装清晰。"
        reference = "本地 03《竹间观云》用侧光和小瓶组织尺度，16 让天空成为留白。"
    elif style == "photo-grid":
        composition = style
        methods.append("layout-grid")
        mechanism, feature, detail = "原片取景与编辑线", "原图边缘、视线或运动方向", ""
        concept = "完整保留原片，用真实的取景框边缘对齐标题与边注。选择一处结构线延伸阅读，边角让信息区与照片保持联系。"
        reference = "本地 24→25、32→33、34→35 分别借实物边、建筑边和道路方向组织图文。"
        mode = plan.get("design", {}).get("photoLayout")
        if mode in ("time", "clock-object", "object"):
            mechanism = "到店时间与实物对角呼应" if mode in ("time", "clock-object") else "实物纹理与原色轮廓"
            concept = ("让商家给出的时间占据上方大字区，标题和商品在左下和右下接力。"
                       if mode in ("time", "clock-object") else "将实物内的一处纹理放大为底色，短标题落在留白里，完整商品从对角接住目光。")
        if mode == "bleed":
            mechanism = "原片延色与关系网格"
            concept = "原片贴近画幅边缘，延续边缘光色。按实际标题行数给字区留量，横幅按照片和文字的分栏重新排印。"
    elif style == "riso":
        methods += ["mono-color", "photo-riso-poster"]
        brief = positive
        colors = {
            "蓝": "#2148B8",
            "绿": "#008A4B",
            "红": "#C83232",
            "橙": "#C65F38",
            "黑": "#30343A",
            "紫": "#63365F",
        }
        # Read printing instructions separately from descriptions of product colors.
        named = re.findall(r"([蓝绿红橙黑紫])(?:墨|色油墨|色印刷)", brief)
        named = list(dict.fromkeys(colors[c] for c in named))
        one = bool(re.search(r"单色|一色|一种墨|monochrome", brief, re.I))
        if len(named) == 1 and not re.search(r"双色|两色|两种墨", brief):
            one = True
        ink = next(iter(named), "#2148B8")
        accent = (
            named[1]
            if len(named) > 1
            else ("#2148B8" if ink == "#C65F38" else "#C65F38")
        )
        print_palette = {
            "paper": "#E9E9E5" if optics else "#F5F1E8",
            "ink": ink,
            "accent": ink if one else accent,
        }
        mechanism, feature, detail = "孔版实物档案", "原图中的轮廓与局部结构", ""
        concept = "将实拍画面的边缘与明暗提取成网点近景，保留原色实物作识别依据。主标题和局部共享边线，纸面留白承接阅读。"
    elif style == "ipscene":
        methods += ["brand-ip-kit", "ip-scene-poster", "ip-consistency-lock"]
        mechanism, feature, detail = "角色场景叙事", "原稿中的角色与配件", ""
        story = next(
            (
                v.strip()
                for v in re.split("[。；！]", plan["original"])
                if re.search("在.{1,35}(摘|拿|走|举|递|招手|托|捧|伸手)", v)
            ),
            plan["original"][:120],
        )
        orchard = bool(re.search("橘园|橙园|柑橘园|果园", story))
        concept = f"从需求取出场景动作「{story[:140]}」。按参考图保留脸形、肢体比例、配件与色块，主体视线朝向场景主物。"
    elif optics and style in ("product", "editorial"):
        mechanism, feature = "黑暗舞台", "机身轮廓"
        detail = next(
            (
                v
                for v in ("金属镜头卡口", "镜头卡口", "红色饰条", "黑色握柄")
                if v in facts
            ),
            "",
        )
        concept = "光从画外落到机身，将真实轮廓和金属反射连成一条视线。"
        reference = "本地 03《竹间观云》以侧光交代物件，留出大片暗部。"
        if style == "product" and source != "photograph" and re.search("取景投影|风景投影|投影光束|型号大字", positive):
            composition = "projection"
            mechanism = "取景投影"
            concept = "让画外风景沿一束收窄的光指向机身卡口；真实机身压住从档案提取的型号字，中文标题落在光束下缘的纸面，视线沿同一方向折回商品。"
            model_mark = re.search(
                r"(?<![A-Za-z0-9])[A-Za-z]{1,5}[- ]?\d{1,4}[A-Za-z]*(?![A-Za-z0-9])",
                profile.get("product", ""),
            )
            if model_mark and type_requested and plan.get("lettering") not in ("off", "han"):
                mark = model_mark.group()

    elif style == "product" and source == "cutout" and not type_requested and re.search(
        "搅开|奶纹|分层纹理|放大纹理|纹理特写|材质特写", positive
    ):
        composition = "material"
        mechanism, feature, detail = "实物与纹理的尺度对照", "原图主体内部的色纹", ""
        concept = "让主体内部的一小块真实纹理铺展成满幅环境，把完整商品放回同一色域。第一眼看见纹理走向，第二眼在实物上找到出处，短标题沿安静的一侧落笔。"
        reference = "本地 24→25 的石材裁切将触感放大，11《芒种》让字的走势接住物体的线。"
    elif style == "product" and type_requested and (
        ingredient := re.search(
            r"抹茶|咖啡|乌龙|红茶|绿茶|茉莉|蘑菇|饺子|草莓|苹果|柑橘|虾|面包", context
        )
    ):
        composition = "ingredient"
        mechanism, feature, detail = "食材字形与实物穿插", ingredient.group(), ""
        mark = (
            ingredient.group() if plan.get("lettering") not in ("off", "latin") else ""
        )
        concept = "从实物名称取一个食材词，宋体放大作为背景，再用原照片的轮廓切开笔画。标题在底部留白独立可读，色墨取自商品本身，价格与条件单列。"
        reference = "本地 01《食得自然》用菌盖和菌柄衔接横竖两组笔画。"
    elif style == "swiss":
        mechanism, feature, detail = "理性极简", "商品与已确认的价格", ""
        concept = "以商品轮廓为价格数字的对齐边，价格、单位和适用条件维持同一阅读顺序。"
    elif style == "editorial":
        mechanism, feature, detail = "负空间微距", "实物材质", ""
        concept = "从真实表面的明暗交界切入，沿边缘负空间排题，远景交代完整外观。"
    elif style == "screenprint":
        mechanism, feature, detail = "Editorial 遮挡", "活动主体的剪影", ""
        concept = "将最能代表活动的实物作为前景，与标题形成前后层次，商品标记始终可辨。"
    else:
        mechanism, feature, detail = "极简商业视觉", "商品轮廓", ""
        concept = "以实物的支撑点为重心，让标题的边线回应商品与背景的交界。"
    if source == "photograph" and style == "product":
        composition, mark = "photograph", ""
        mechanism = "原片取景"
        concept = "保留整张原片的真实环境与光线，从照片边缘延续色调，在画外余量安排准确标题，让顾客看清原片里的商品。"
        reference = "本地 34→35 保留骑行轴线，在空旷的环境安排字。"
    reading = plan.get("design", {}).get("readingOrder")
    if reading:
        methods.append("hiccai-poster-taste")
        concept += reading["direction"] + reading.get("layoutReason", "")
    return {
        "skill": "hiccai-poster",
        "methods": methods,
        "composition": composition,
        "lighting": lighting,
        "modelMark": mark,
        "print": print_palette,
        "story": story,
        "orchard": orchard,
        "revision": REVISION,
        "mechanism": mechanism,
        "reference": reference,
        "optics": optics,
        "concept": f"围绕「{product}」：{concept}",
        "feature": detail or focus or feature,
        "detail": detail,
    }


def poster_reading(plan, copy):
    """Choose the first read from the approved copy and available source."""
    brief = visual_requests(plan["original"])
    role = plan.get("bundleRole")
    if role not in (None, "hero", "cover", "campaign", "promotion", "price", "banner"):
        return None
    design = plan.get("design", {})
    selected = design.get("selection", "auto")
    if plan.get("layoutOverride") or selected not in ("auto", "photo-grid"):
        return None
    requested = requested_style(plan["original"])
    if requested not in (None, "photo-grid") or "满屏字" in brief:
        return None
    if plan.get("posterArt", {}).get("composition") in ("material", "ingredient", "projection", "riso", "ipscene"):
        return None
    if re.search(r"(?:不要|不用|避免|不使用)(?:使用)?照片编排", plan["original"]):
        return None
    if re.search(r"标题优先|文字优先|先读标题", brief):
        return dict(first="title", direction="先读标题，原片与标题共享边线。")
    suppress_price = re.search(r"(?:不要|避免|不用|别)(?:突出|放大|强调)(?:优惠|折扣|价格|售价|数字)", plan["original"])
    picture_first = re.search(r"照片优先|商品优先|先看商品|先看照片", brief)
    promotion = role in ("campaign", "promotion", "price") or re.search(r"促销|优惠|满减|折扣|半价|买.{1,4}送|价目", brief)
    if copy.get("offer") and promotion and not (suppress_price or picture_first):
        return dict(first="offer", direction="先读已确认的优惠，适用条件紧接优惠，标题保留在独立读区。")
    if plan.get("photoFeatures") or picture_first or role == "hero" or re.search(r"上新|新品|上市|上架|首发|全图|满版摄影", brief):
        observed = (plan.get("sourceReview") or {}).get("visualDetail") or {}
        if plan.get("visualSource") in ("cutout", "photograph"):
            subject = "原图中的「" + observed["label"] + "」" if observed.get("label") else "原图商品的完整轮廓"
        else:
            subject = "与商品相关的示意主视觉"
        return dict(first="product", direction="先看" + subject + "，为主体留出连续图幅，再读标题；售价和条件作辅助信息。")
    if suppress_price or "取景框" in brief or "photo-grid" in (selected, requested, design.get("id")):
        return dict(first="title", direction="标题先交代主题，整张照片与标题共享边线。")
    return None


def first_draft_treatment(plan, reading, *, transaction_copy=False, motif=None):
    """Choose a rendering treatment without changing the approved reading order."""
    original = plan["original"]
    brief = visual_requests(original)
    negative = r"(?:不要|不用|避免|别用|不使用|不想要)(?:再|使用|做成|用)?"
    no_bleed = bool(re.search(negative + r"(?:全图|满版)", original))
    no_frame = bool(re.search(negative + "取景框", original))
    if "取景框" in brief and not no_frame:
        return "photo-grid", "framed", "保留取景框，将文字和原片分区。"
    if not no_bleed and re.search(r"全图|满版摄影|照片铺满|原图铺满|铺满整张", brief):
        return "photo-grid", "bleed", "用完整照片和延展边色铺开主画面。"
    if no_bleed:
        return "quiet-light", None, "按要求缩小商品照片，周围留出连续字区。"
    if reading["first"] != "product":
        return "photo-grid", "bleed", "保留完整画面，首要文字与说明在照片延展区成组排印。"

    photo = plan.get("photoFeatures")
    if not photo:
        return "photo-grid", "bleed", "由满版画面承载品名和说明，按实际素材安排图文空间。"
    grid_requested = plan["design"].get("selection") == "photo-grid" or requested_style(original) == "photo-grid"
    output = plan.get("output") or {}
    aspect = output.get("width", 1080) / output.get("height", 1440)
    fit = min(aspect / photo["aspect"], photo["aspect"] / aspect)
    calm = photo["calmArea"]
    detailed = photo["edgeDensity"] >= 0.14 and photo["tonalRange"] >= 65
    energetic = re.search(r"市集|摊位|快闪|派对|联名|乐队|复古|热闹|抢眼|醒目|有劲|年轻人", brief)
    quiet = re.search(r"慢下来|慢一点|安静|清静|放松|独处|歇一会|坐一会|喘口气|清晨|午后|温柔|克制", brief)
    natural = re.search(r"原色|真实颜色|自然一点|日常|实拍感|不要.{0,4}(?:滤镜|改色|花哨|太花|网点|印刷|孔版)", original)
    if not grid_requested:
        if plan.get("moment") and aspect <= 1 and not (transaction_copy or plan.get("brandKit", {}).get("logo")):
            if motif == "columns" and plan.get("visualSource") == "cutout":
                return "photo-grid", "columns", "把实拍放在横向表格的最后一列，列标接住同事之间的玩笑。"
            if motif == "reply" and plan.get("visualSource") == "cutout":
                return "photo-grid", "reply", "让实拍水杯像在回消息，气泡尖角指向杯盖。"
        if detailed and energetic and not natural and not quiet and not re.search(negative + r"(?:双[色墨]|孔版|网点|印刷)", original):
            return "riso", None, "活动需要远看醒目，原片的明暗和边缘适合提取双色网点，旁边保留原色商品。"
        if not re.search(negative + r"(?:留白|暗调|暗底|黑底|深色)", original):
            if quiet and (calm >= 0.12 or photo["tonalRange"] >= 80):
                return "quiet-light", None, "给安静的场景留出空间，借原片的光色承托缩小后的商品。"
            if calm >= 0.48 and photo["brightness"] < 92 and plan.get("visualSource") != "cutout":
                return "quiet-light", None, "原片有大块平静暗部，延续原有明暗，在主体周围留白。"
    if (plan.get("moment") and plan.get("visualSource") == "cutout" and aspect <= 1
            and not (grid_requested or transaction_copy or plan.get("brandKit", {}).get("logo"))):
        if plan["moment"].get("clock"):
            if plan["moment"].get("roundSubject"):
                return "photo-grid", "clock-object", "实拍物体的圆形轮廓接替时间末位的零，另排完整时间和经营说明。"
            return "photo-grid", "time", "将确认的到店时间放成大数字，实物轮廓和数字沿对角线相接。"
        return "photo-grid", "object", "从实物取局部纹理与色调，放大轮廓形成前景，以连续留白承接标题。"
    if plan.get("visualSource") != "cutout" and (calm < 0.23 or fit < 0.58):
        return "photo-grid", "bleed", "保留完整原片，沿照片边缘延展底色排字，让标题避开密集细节。"
    return "photo-grid", "bleed", "原片主体可完整放大，标题沿照片边缘另排。"
