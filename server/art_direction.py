"""Product-specific art direction adapted from hiccai-poster, revision 46994ee."""

import re
from .design import visual_requests

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
        mechanism, feature, detail = "原片取景与编辑线", "原图边缘、视线或运动方向", ""
        concept = "完整保留原片，用真实的取景框边缘对齐标题与边注。选择一处结构线延伸阅读，边角让信息区与照片保持联系。"
        reference = "本地 24→25、32→33、34→35 分别借实物边、建筑边和道路方向组织图文。"
        if plan.get("design", {}).get("photoLayout") == "bleed":
            methods.append("layout-grid")
            mechanism = "原片延色与关系网格"
            concept = "原片贴近画幅边缘，延续边缘光色。按实际标题行数给字区留量，横幅从照片读向文字，有优惠时把数字与适用条件成组。"
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
