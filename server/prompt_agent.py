"""Interpret the brief once and compile the approved direction for each production stage."""

import re
from . import model, wenan
from .campaign import LOCKED, copy_route, offer_and_terms
from .creative import METHODS, promotion_terms
from .design import DIRECTIONS, choose_style

PACE = {
    "steady": "自然推进",
    "quiet": "轻缓推进，留出观察时间",
    "brisk": "快速推近，用尺度变化强调细节",
}
TREATMENTS = {
    "product": "让一件商品占据主画面，用光线分开主体和背景。",
    "editorial": "扩大连续留白，减少道具，让材质与字形产生对照。",
    "swiss": "先读活动利益与条件，再读品名，数字与包装分开落位。",
    "screenprint": "用有限色和物件轮廓组织前后景，保留真实商品颜色。",
}


def local_reading(plan):
    brief = plan["original"]
    clauses = [s.strip() for s in re.split(r"[，。；！\n]", brief) if s.strip()]

    def excerpt(pattern):
        return next((s[:90] for s in clauses if re.search(pattern, s)), "")

    row = copy_route(plan)
    options = [plan["profile"].get("product", ""), (row or {}).get("product", "")]
    product = next((v for v in options if v and v in brief), "")
    if not product and row:
        matched = re.search(row["match"], brief, re.I)
        product = matched.group() if matched else ""
    if not product:
        named = re.search(
            r"(?:给|为|推广|宣传)(?:我的|这款|我们的)?([^，。！？、]{2,18}?)(?:做|写|拍|设计|制作)",
            brief,
        )
        if named:
            product = named.group(1)
    target = re.search(r"(?:面向|目标客群是|想卖给|主要给)([^，。；！\n]{2,24})", brief)
    method = plan["method"]
    if re.search("悬念|开头.{0,6}(抓人|吸睛)|先问", brief) and not re.search(
        "不要.{0,5}(悬念|问句)", brief
    ):
        method = "question"
    elif re.search("邀约|邀朋友|喊朋友", brief):
        method = "invite"
    style = plan.get("design", {}).get("id", "product")
    if (
        re.search("高级感|高级点|克制|杂志感", brief)
        and not re.search("不要.{0,5}(高级|克制|杂志)", brief)
        and style in ("product", "swiss")
        and not re.search("价格主视觉|放大价格|突出价格|促销网格|瑞士", brief)
    ):
        style = "editorial"
    return dict(
        product=product or plan["profile"].get("product") or plan["subject"],
        audience=target.group(1) if target else plan["audience"],
        focus=excerpt("突出|重点|主打|卖点|强调"),
        visual=excerpt("光线|背景|色调|逆光|留白|构图|配色|不要.{0,5}(颜色|色|背景)"),
        method=method,
        style=style,
        pace="quiet"
        if re.search("慢一点|慢节奏|舒缓|安静", brief)
        else "brisk"
        if re.search("快节奏|动感|活泼|节奏快", brief)
        else "steady",
    )


def optimize(spec, *, infer=True, previous=None):
    plan = spec["plan"]
    kind = spec["kind"]
    reading = local_reading(plan)
    engine = "本地提示词规则"
    channels = {
        "copy": ["copy"],
        "poster": ["copy", "image"],
        "video": ["copy", "image", "video"],
    }[kind]
    refinements = {}
    constraints = [
        v.strip()
        for v in re.split("[，。；！\n]", plan["original"])
        if re.search("不要|必须|保留|禁止|不能|只用|避免", v)
    ]
    if previous:
        reading.update(previous["reading"])
        reading["method"] = plan["method"]
        reading["style"] = plan.get("design", {}).get("id", reading["style"])
        # A changed angle or layout gets fresh instructions, even on an older work.
        engine = "本地提示词规则"
    elif infer and model.engine_name() != "本地创意规则":
        # Freeform business claims must never become a new source of evidence.
        sources = [
            plan["original"],
            plan.get("facts", ""),
            *(str(v) for v in plan["profile"].values() if v),
        ]
        try:
            result, name = model.ask(
                "你是 Trupic 的创作提示词策划。理解商家口语，区分真实卖点、目标受众和表现手法。根据素材和媒介选择执行方向。"
                "只输出 JSON。product、audience、focus、visual 分别逐字摘取原文中的商品、受众、想突出的事实或动作、视觉约束，保留否定和限定词；不确定留空。"
                "method 选 moment/question/invite，style 选 product/editorial/swiss/screenprint，pace 选 steady/quiet/brisk。优先明确要求与已选版式。"
                "还要返回 directions 对象，只填写媒介需要的 copy/image/video 键，每项写一至两句本次专用的创作提示词。把空泛形容词翻成能执行的动作、镜头、构图或句式，说明图文如何配合。用户的禁区和已有素材不可改变。不要写示例广告语、额外商品特性或任何新商业事实。",
                {
                    "需求": plan["original"],
                    "档案": {
                        k: plan["profile"].get(k, "")
                        for k in (
                            "name",
                            "product",
                            "facts",
                            "audience",
                            "tone",
                            "industry",
                        )
                    },
                    "补充事实": plan.get("facts", ""),
                    "媒介": kind,
                    "已选版式": plan.get("design"),
                    "输出规格": plan.get("output"),
                    "初步分析": reading,
                    "有商品图": bool(spec["asset"]),
                },
                320,
            )
            valid = {}
            for k in ("product", "audience", "focus", "visual"):
                v = result.get(k)
                if (
                    isinstance(v, str)
                    and 0 < len(v.strip()) <= 90
                    and any(v.strip() in s for s in sources)
                ):
                    valid[k] = v.strip()
            for k, options in (
                ("method", METHODS),
                ("style", TREATMENTS),
                ("pace", PACE),
            ):
                if isinstance(result.get(k), str) and result[k] in options:
                    valid[k] = result[k]
            proposed = result.get("directions")
            if isinstance(proposed, dict):
                candidates = {
                    k: proposed[k].strip()
                    for k in channels
                    if isinstance(proposed.get(k), str)
                    and 4 <= len(proposed[k].strip()) <= 240
                }
                if candidates:
                    review, _ = model.ask(
                        '复核策划指令是否忠实于原需求和已确认资料，是否擅加事实、改变优惠条件、违反否定要求或指定版式。全部忠实且可执行才返回 JSON {"ok":true}。',
                        {
                            "source": sources,
                            "kind": kind,
                            "design": plan.get("design"),
                            "directions": candidates,
                        },
                        80,
                    )
                    if review.get("ok") is True:
                        refinements = candidates
                    else:
                        valid.clear()
            if valid or refinements:
                reading.update(valid)
                engine = name
        except Exception:
            pass
    if plan.get("lettering") == "auto":
        if re.search("不要装饰字|关闭装饰字|不用装饰字", plan["original"]):
            plan["lettering"] = "off"
        elif re.search("不用英文装饰|不要英文装饰|只用中文装饰", plan["original"]):
            plan["lettering"] = "han"
    plan["method"] = reading["method"]
    plan["angle"] = METHODS[plan["method"]]
    plan["audience"] = reading["audience"]
    design = plan.get("design")
    if design:
        if design["selection"] == "auto" and reading["style"] != design["id"]:
            plan["design"] = {
                **choose_style(plan, reading["style"]),
                "selection": "auto",
            }
        reading["style"] = plan["design"]["id"]
    product = reading["product"]
    offer, terms = offer_and_terms(plan, promotion_terms)
    locked = LOCKED.search(plan["original"])
    anchors = [
        x for x in (plan.get("facts"), plan["profile"].get("facts"), offer, terms) if x
    ]
    action = wenan.conversion(plan, product)
    if action:
        plan["goal"] = {
            "下单": "引导下单",
            "到店": "邀请顾客到店",
            "询问": "引导顾客询问",
            "预约": "引导咨询预约",
        }[action["goal"]]
    copy = f"为{reading['audience']}写关于「{product}」的内容，目标是{plan['goal']}。{plan['angle']}。"
    copy += {
        "poster": "主标题只承担一个重点，价格与条件留给次级文字。",
        "copy": "用一个具体场景开篇，解释一个选择理由，结尾给一个行动。",
        "video": "开头写能在前三秒读完的一句，中段增加一条信息，末镜只给一个行动。",
    }[kind]
    if action:
        copy += (
            "本次以「"
            + action["goal"]
            + "」收口。正文承接标题，落到一个动作，参考末句「"
            + action["line"]
            + "」。"
        )
    if wenan.social_headline(plan):
        copy += wenan.social_brief(plan)
    if wenan.no_cta(plan):
        copy = copy.replace("结尾给一个行动", "结尾停在品牌主张").replace(
            "末镜只给一个行动", "末镜收在品牌或品名"
        )
    if tone := plan["profile"].get("tone"):
        copy += "品牌语气采用「" + tone + "」。"
    if reading["focus"]:
        copy += "优先回应商家这句要求：「" + reading["focus"] + "」。"
    if anchors:
        copy += "保留资料与限定条件：" + "；".join(dict.fromkeys(anchors)) + "。"
    if locked:
        copy += "指定标题逐字保留：「" + locked.group(1) + "」。"
    copy += "仅以原需求和商家资料作为经营事实依据。"
    copy += (
        " 按 hiccai-wenan v"
        + wenan.VERSION
        + " 的「"
        + "、".join(wenan.sections(plan))
        + "」要求成稿并核对。"
    )
    prompts = {"copy": copy}
    if kind != "copy":
        out = plan.get("output") or {}
        art = DIRECTIONS.get(plan.get("sector"), DIRECTIONS["general"])
        visual = (
            f"围绕「{product}」设计全幅主视觉。"
            + TREATMENTS[reading["style"]]
            + art["shot"]
        )
        if out:
            visual += f"按 {out['width']} × {out['height']} 构图。"
        if reading["visual"]:
            visual += "商家的视觉要求：「" + reading["visual"] + "」。"
        visual += (
            "只设计空背景，商家原图主体在本地合成。"
            if spec["asset"]
            else "制作无品牌概念场景。"
        ) + "文字另行排版。"
        prompts["image"] = visual
    if kind == "video":
        prompts["video"] = (
            f"以「{product}」为主体。0–3 秒{plan['angle']}，3–6 秒推进商品细节，6–9 秒回到全景并给出行动。镜头节奏采用{PACE[reading['pace']]}。"
        )
    if "video" in prompts and action:
        prompts["video"] += "末镜清楚显示本次" + action["goal"] + "行动。"
    if "video" in prompts and wenan.no_cta(plan):
        prompts["video"] = prompts["video"].replace("并给出行动", "并以品牌或品名收束")
    for channel in prompts:
        if channel in refinements:
            prompts[channel] += " " + refinements[channel]
        if constraints:
            prompts[channel] += " 原文要求：" + "；".join(constraints) + "。"
    plan["promptBrief"] = {"reading": reading, "engine": engine, "prompts": prompts}
