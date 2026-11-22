"""Creative planning, licensed reference methods, and grounded copy generation."""

import copy as copylib
import datetime as dt
import hashlib
import json
import re

from . import model, wenan
from .campaign import (
    LOCKED,
    benefit_scene,
    complete_body,
    copy_angle,
    copy_route,
    offer_and_terms,
)
from .design import DIRECTIONS, direction

CASES = [
    dict(
        id="matcha",
        title="把春意，装进一杯抹茶",
        industry="茶饮咖啡",
        kind="营销海报",
        method="让颜色先说话",
        lesson="从饮品本身取一个主色，把文字与产品放在同一个视觉焦点上。",
        brief="为抹茶饮品做一张海报，面向午休想放松一下的上班族，用绿色和留白表达轻松感。",
    ),
    dict(
        id="pool",
        title="下班之后，球桌见",
        industry="休闲娱乐",
        kind="营销海报",
        method="从下班的瞬间切入",
        lesson="让球杆斜线把视线引向白球，再用一句邀请把下班与碰面连起来。",
        brief="帮我宣传台球室，吸引下班后想和朋友见面的人，从开球前的一秒切入。",
    ),
    dict(
        id="citrus",
        title="一口柑橘，唤醒午后",
        industry="茶饮咖啡",
        kind="营销海报",
        method="放大一个感官细节",
        lesson="用柑橘切面和气泡的细节接住标题，让读者先想到一口饮料的感觉。",
        brief="给柑橘饮品做宣传，用切开的橙子和午后的光线，邀请附近的顾客来喝一杯。",
    ),
    dict(
        id="bakery",
        title="早晨从一只可颂开始",
        industry="烘焙甜品",
        kind="营销海报",
        method="把商品放回生活里",
        lesson="用早餐桌面建立消费场景，围绕一个具体时刻呈现商品。",
        brief="为面包店的可颂写一份早餐推广，用通勤前的早晨作为创意起点。",
    ),
]
# Each brief can lead with a scene, a question, or an invitation.
SCENES = [
    (
        "台球|桌球|球房",
        "台球",
        "下班以后，开一局",
        "今晚，谁先开球？",
        "把见面约在球桌边",
        "把群聊里的「改天见」换成一声开球。约上那个总说有空的朋友，今晚在球桌边碰面。",
        "喊上球友，一起来开球。",
        "撞球的一瞬",
        "pool",
    ),
    (
        "火锅|锅底|涮肉|聚餐",
        "火锅",
        "人到齐，就开涮",
        "今晚，谁来下第一筷？",
        "把群聊搬到锅边",
        "聊天框里说不完的话，留到同一张桌上。围着锅坐下，先问问朋友今天想涮什么。",
        "把这顿饭发给想见的人。",
        "围桌的距离",
        "",
    ),
    (
        "抹茶|奶茶|茶饮|咖啡|柑橘|饮品|果茶|饮料",
        "饮品",
        "把午后留给这一杯",
        "今天，想喝哪一杯？",
        "碰个杯，再出发",
        "工作告一段落，给自己留一杯的时间。一个人慢慢喝，或约上身边的朋友，把今天的闲聊放进午后。",
        "约个时间，一起来喝一杯。",
        "手边的一杯",
        "matcha",
    ),
    (
        "面包|可颂|烘焙|甜品|蛋糕",
        "烘焙",
        "早一点，遇见好滋味",
        "明早，想带走哪一口？",
        "给早餐留个位置",
        "出门之前，先把早餐安排好。给自己挑一份喜欢的，也可以给同行的人捎上一份。",
        "路过时，进店挑一份。",
        "清晨的第一口",
        "bakery",
    ),
    (
        "美容|护肤|美甲|护理|美发",
        "日常护理",
        "给自己留一点时间",
        "你的护理习惯是什么？",
        "从一个小习惯聊起",
        "把日常护理里最拿不准的小问题记下来。聊清自己的习惯，再一起看看适合从哪一步开始。",
        "带着你的问题来聊聊。",
        "日常的一刻",
        "",
    ),
    (
        "花店|花束|鲜花|花艺",
        "花艺",
        "挑一束，带回今天",
        "这束花，想送给谁？",
        "给平常的一天送束花",
        "想起一个人的时候，不妨把心意放进一束花里。来看看今天喜欢的颜色，挑给对方，也挑给自己。",
        "说说想送花的人，一起挑一束。",
        "挑选花束的瞬间",
        "",
    ),
    (
        "书店|图书|阅读",
        "阅读",
        "给下一页留点时间",
        "下一本，想读什么？",
        "来书架旁碰个面",
        "沿着书架慢慢走，会遇见原本没打算寻找的那一本。把今天感兴趣的话题带来，给自己留一段阅读时间。",
        "到店翻一翻，再做选择。",
        "翻开一页",
        "",
    ),
    (
        "服装|穿搭|衣服|穿搭",
        "穿搭",
        "给今天换种穿法",
        "下一次见面，怎么穿？",
        "一起挑一身喜欢的",
        "从日程里挑一个具体的场合，再想今天想穿成什么样。把喜欢的颜色记下来，到店慢慢搭配。",
        "带上你的搭配想法来看看。",
        "出门前的搭配",
        "",
    ),
    (
        "健身|瑜伽|运动",
        "运动",
        "今天，给身体一点时间",
        "下班后，一起动一动？",
        "把约定放进日程",
        "忙了一天，给自己留出一段活动的时间。找个合拍的朋友，把下一次见面约在运动时。",
        "约上伙伴，来了解一下。",
        "出发前一刻",
        "",
    ),
]
FALLBACK = (
    "",
    "门店",
    "把今天的好发现分享给你",
    "这次，想为谁挑选？",
    "给日常添个新选择",
    "有时候，一个合适的选择就藏在路过的街角。带着自己的需要，到店看看，也聊聊你的想法。",
    "来店里，找到你喜欢的。",
    "日常的发现",
    "",
)
METHODS = {
    "moment": "从生活瞬间切入",
    "question": "用一个问题开场",
    "invite": "用邀请带出行动",
}
RISK = re.compile(
    r"全网第一|全市第一|100%有效|百分百有效|保证治愈|包治百病|永久治愈|零风险"
)
UNKNOWN = re.compile(
    r"(?:打折|折扣|优惠价|满减|优惠力度|价格|折数|售价).{0,7}(?:待定|随便编|你来定|没定|未定)|(?:编造|捏造|虚构).{0,12}(?:价格|折扣|优惠|功效|销量)"
)
NUMCLAIM = re.compile(
    r"\d+(?:\.\d+)?\s*(?:元|折|%|％|天|小时|年|分钟|份|杯|位|人|家|店|斤|克)"
)


def scene_for(text, profile):
    for source in [
        text,
        " ".join(str(profile.get(k, "")) for k in ("product", "industry", "facts")),
    ]:
        for scene in SCENES:
            if re.search(scene[0], source):
                return scene
    return FALLBACK


def uidnum(value):
    return int(hashlib.sha256(value.encode()).hexdigest()[:10], 16)


def prepare(brief, profile, history, rule, reference="", facts=""):
    sector, art = direction(brief, profile)
    saved_sector = direction("", profile)[0]
    if sector != saved_sector and saved_sector != "general":
        profile = {
            k: v
            for k, v in profile.items()
            if k not in ("industry", "product", "facts")
        }
    context = " ".join([brief, facts, profile.get("facts", "")])
    if RISK.search(context):
        raise ValueError(
            "需求或商家档案里含有绝对化承诺。请换成有依据的经营信息，再开始创作。"
        )
    if UNKNOWN.search(context) and not facts.strip():
        raise ValueError("请把待定的优惠或价格改为已确认的具体信息，或先去掉促销要求。")
    sc = scene_for(brief, profile)
    if sc == FALLBACK and sector != "general":
        sc = (
            *sc[:1],
            art["name"],
            *sc[2:7],
            {
                "auto": "看见车身的线条",
                "commerce": "靠近，看见细节",
                "clean": "从一件日常小事开始",
                "home": "触摸日常的纹理",
                "retail": "走进今天的好发现",
                "beauty": "看见光落在瓶身",
            }.get(sector, sc[7]),
            sc[8],
        )
    goal = next(
        (
            label
            for pattern, label in [
                ("新客|第一次", "邀请新客进店"),
                ("复购|回购|老客", "邀请老客再次到店"),
                ("知识|科普", "分享实用知识"),
                ("预订|预约", "引导咨询预约"),
                ("上新|新品", "介绍新商品"),
                ("朋友|聚餐|组局", "邀请朋友相聚"),
            ]
            if re.search(pattern, brief)
        ),
        "引起兴趣并引导到店",
    )
    audience = profile.get("audience") or next(
        (
            a
            for a in ["上班族", "年轻人", "学生", "朋友", "老顾客", "附近居民", "家庭"]
            if a in brief
        ),
        "附近可能对" + sc[1] + "感兴趣的人",
    )
    method = rule["method"]
    if "？" in brief or "悬念" in brief:
        method = "question"
    if goal in ("邀请朋友相聚", "邀请老客再次到店"):
        method = "invite"
    used = [w.get("method") for w in history[:3]]
    if method in used[:1]:
        method = next(m for m in METHODS if m != method and m not in used[:1])
    match = next((c for c in CASES if c["id"] == reference), None)
    if not match:
        match = CASES[(list(METHODS).index(method) + uidnum(sc[1]) % 3) % len(CASES)]
    photo = {"台球": "pool", "火锅": "hotpot", "日常护理": "care"}.get(sc[1], "")
    context = brief + " " + profile.get("product", "")
    for pat, what in (
        ("抹茶", "matcha"),
        ("柑橘|橙汁|鲜橙", "citrus"),
        ("可颂|牛角包", "bakery"),
    ):
        if re.search(pat, context):
            photo = what
            break
    if art.get("plateMatch") and re.search(art["plateMatch"], context, re.I):
        photo = art["plate"]
    elif sector not in ("general", "tea"):
        photo = ""
    return dict(
        sector=sector,
        scenePhoto=photo,
        method=method,
        angle=METHODS[method],
        goal=goal,
        audience=audience,
        subject=sc[1],
        reference=match["method"],
        referenceId=match["id"],
        shot=sc[7],
        rule=rule["name"],
        ruleId=rule["id"],
        original=brief,
        facts=facts,
        profile=profile,
        recent=[x.get("title", "") for x in history[:3]],
    )


def promotion_terms(brief):
    conditions = re.compile(
        r"^(?:本周末(?:供应|有效|适用)|仅(?:限|供|面向)|限(?:堂食|外带|本店|到店|每人|每桌|每单)|每(?:位|人|单|桌)限|不可(?:叠加|同享)|不(?:与其他优惠|适用|参与)|活动(?:时间|日期)|有效期|截至)"
    )
    clauses = (part.strip() for part in re.split(r"[，。；！？\n]", brief))
    return "，".join(dict.fromkeys(part for part in clauses if conditions.match(part)))


def draft_copy(plan, variant=0):
    brief, prof = plan["original"], plan["profile"]
    sc = scene_for(brief, prof)
    index = (list(METHODS).index(plan["method"]) + variant) % 3
    title = sc[2 + index]
    body = sc[5]
    cta = sc[6]
    interpreted = plan.get("promptBrief", {}).get("reading", {}).get("product", "")
    product = (interpreted if interpreted != plan["subject"] else "") or prof.get(
        "product", ""
    ).strip()
    for word in [
        "热可可",
        "燕麦拿铁",
        "茉莉奶绿",
        "草莓蛋糕",
        "番茄锅底",
        "桂花乌龙",
        "抹茶拿铁",
        "桂花拿铁",
        "柑橘气泡水",
        "芝士蛋糕",
        "抹茶",
        "柑橘",
        "可颂",
        "奶茶",
        "生椰拿铁",
    ]:
        if word in brief:
            product = word
            break
    if sc == FALLBACK and not product and plan.get("sector", "general") == "general":
        found = re.search(
            r"(?:宣传|推广|介绍|上新|为)([\u4e00-\u9fffA-Za-z0-9]{2,12}?)(?:做|写|的|[，。！、\s]|$)",
            brief,
        )
        product = found.group(1) if found else prof.get("name", "")
    sector = plan.get("sector", "general")
    if sc == FALLBACK and sector != "general":
        art = DIRECTIONS[sector]
        title = (art["headline"], plan["shot"], "挑选" + (product or art["name"]))[
            index
        ]
        body, cta = art["copy"], art["cta"]
    elif sc == FALLBACK and product:
        title = (product, product + "怎么挑？", "这次，看看" + product)[index]
    use_social = wenan.social_headline(plan)
    direction = copy_angle(plan, index, use_social)
    if use_social and not direction and product and sc == FALLBACK:
        # For an unfamiliar SKU, give the audience a use for the line without inventing specifications.
        title = (
            f"刚看到{product}，就想到你。",
            f"你挑{product}，第一眼看哪儿？",
            f"你挑{product}的眼光，借我用一下。",
        )[index]
    if direction:
        title, body, cta = direction["title"], direction["body"], direction["cta"]
    if plan["goal"] == "分享实用知识":
        title = "关于" + (product or sc[1]) + "，你想问什么？"
        body = "挑选之前，先想清使用场景和自己的偏好。把最想了解的问题写下来，我们从你的实际需要聊起。"
    if plan["goal"] == "引导咨询预约" and "试驾" not in brief:
        cta = "发来方便的时间，我们约着见。"
    if prof.get("tone") == "简洁直接":
        body = re.split(r"(?<=[。！？])", body, maxsplit=1)[0]
    offer, terms = offer_and_terms(plan, promotion_terms)
    locked = LOCKED.search(brief)
    if locked:
        title = locked.group(1)
    if product and product not in title + body:
        body = product + "。" + body
    body = complete_body(plan, body, offer, terms)
    return wenan.apply_local(
        plan,
        dict(
            title=title,
            detailLine=direction.get("detailLine", ""),
            offer=offer,
            terms=terms,
            body=body,
            cta=cta,
            engine="本地创意规则",
            angle=plan["angle"],
            method=plan["method"],
            shot=plan["shot"],
        ),
    )


def generate_copy(plan, variant=0):
    base = draft_copy(plan, variant)
    if model.engine_name() == "本地创意规则":
        return base
    spec = wenan.spec_line(plan)
    skill = wenan.instructions(plan)
    prompt = (
        skill
        + "\n按上述 Skill 和商家要求写成品。只返回 JSON 对象，含 title、body、cta、detailLine。cta 在无需行动引导时可为空。detailLine 为可选的短片中段字幕。目标篇幅按用户要求和当前交付尺寸。"
    )
    if spec:
        prompt += " 本次只交一行已给定的规格，放入 title，body 与 cta 留空。"
    try:
        directions = plan.get("promptBrief", {}).get("prompts", {})
        val, engine = model.ask(
            prompt,
            {
                "plan": plan,
                "writingBrief": directions.get("copy", ""),
                "filmBrief": directions.get("video", ""),
                "variation": variant,
            },
        )
        for k, maxlen in (("title", max(30, len(spec))), ("body", 260), ("cta", 40)):
            if (
                not isinstance(val.get(k), str)
                or not (0 if k == "cta" or (spec and k == "body") else 1)
                <= len(val[k].strip())
                <= maxlen
            ):
                return {**base, "reviewFlag": "模型草稿格式异常"}
        if spec and (
            val["title"].strip() != spec or val["body"].strip() or val["cta"].strip()
        ):
            return {**base, "reviewFlag": "模型草稿格式异常"}
        if wenan.no_cta(plan):
            val["cta"] = ""
        detail = val.get("detailLine", "")
        if not isinstance(detail, str) or len(detail) > 32:
            return {**base, "reviewFlag": "模型草稿格式异常"}
        locked = LOCKED.search(plan["original"])
        if locked:
            val["title"] = locked.group(1)
        content = " ".join((val["title"], val["body"], val["cta"], detail))
        known = (
            plan["original"]
            + " "
            + plan["facts"]
            + " "
            + json.dumps(plan["profile"], ensure_ascii=False)
        )
        guarded = (
            "免费",
            "不限量",
            "无添加",
            "有机",
            "纯天然",
            "现做",
            "手工",
            "进口",
            "包邮",
            "限量",
            "当天送达",
            "医美级",
            "零糖",
            "正品保证",
        )
        if (
            RISK.search(content)
            or any(x not in known for x in NUMCLAIM.findall(content))
            or any(x in content and x not in known for x in guarded)
        ):
            return {**base, "reviewFlag": "模型草稿含未经确认的声明"}
        headline_review = (
            " 单独遮住正文和行动号召审主标题：第一眼读懂了吗，商品和这句话有什么关系？"
            "请在心里指出哪条已知卖点或产品用途让哪种顾客情绪成立；移除卖点后若同一句还成立，退稿。资料不足时只允许有根据的用途。核对目标受众与情绪是否相符。"
            "想象一个具体接收人和一句自然的接话。只有成立才返回 headlineOk 为 true。"
            "靠正文解释、换个商品照样成立、只催转发的标题都应退稿。"
            if wenan.social_headline(plan)
            else ""
        )
        benefit = benefit_scene(plan, copy_route(plan)) if headline_review else None
        if benefit:
            headline_review += " 本稿指定了已确认卖点。标题中的情绪与分享理由必须依赖该卖点，审核通过时在 benefitEvidence 逐字返回所用的卖点原文。"
        action = wenan.conversion(plan)
        action_review = (
            " 独立审末句，核对目标、与商品的关系、入口依据及动作是否唯一。通过时另返 closingOk 为 true。"
            if action
            else ""
        )
        review, _ = model.ask(
            skill
            + "\n本次只执行独立审稿，检查媒介、品牌关联、必含事实和明确禁区。你是独立的事实审核员。核对成品与商家原始需求及档案，拒绝一切未提供的价格、商品特点、优惠或功效。检查文案是否回应营销目标、可读性、行动引导、图片与文案创意是否匹配。返回 JSON：ok 布尔值，reason 简短中文说明。"
            + headline_review
            + action_review,
            {
                "source": known,
                "visual": plan["shot"],
                "goal": plan["goal"],
                "closing": action,
                "benefitEvidence": benefit["evidence"] if benefit else "",
                "draft": val,
            },
            180,
        )
        if (
            review.get("ok") is not True
            or (headline_review and review.get("headlineOk") is not True)
            or (benefit and review.get("benefitEvidence") != benefit["evidence"])
        ):
            return {
                **base,
                "reviewFlag": "模型草稿复核未通过",
                "review": "模型草稿未通过复核，已使用保守版本。",
            }
        if action and (
            review.get("closingOk") is not True
            or not val["cta"].strip()
            or (
                action["channel"]
                and action["channel"] not in val["cta"]
                and not (action["channel"] == "电话" and "来电" in val["cta"])
            )
            or any(
                ch in val["cta"] and ch not in known
                for ch in (
                    "二维码",
                    "扫码",
                    "小程序",
                    "私信",
                    "购物车",
                    "链接",
                    "加微信",
                    "电话",
                )
            )
        ):
            val["cta"] = action["line"]
        return {
            **base,
            **{k: val[k].strip() for k in ("title", "body", "cta")},
            "body": ""
            if spec
            else complete_body(plan, val["body"].strip(), base["offer"], base["terms"]),
            "detailLine": detail or base["detailLine"],
            "writingSkill": wenan.record(plan, "模型创作与复核"),
            "engine": engine,
            "review": str(review.get("reason", "已复核创意与经营事实。"))[:200],
        }
    except Exception:
        return {
            **base,
            "reviewFlag": "模型调用未完成",
            "review": "模型未返回可用内容，已使用本地创意规则。",
        }


def next_suggestion(spec, current):
    p = copylib.deepcopy(spec["plan"])
    start = list(METHODS).index(p["method"])
    for step in range(1, 4):
        p["method"] = list(METHODS)[(start + step) % 3]
        p["angle"] = METHODS[p["method"]]
        result = draft_copy(p)
        if result["title"] != current["title"]:
            break
    if (
        result["title"] == current["title"]
        and not LOCKED.search(p["original"])
        and not wenan.spec_line(p)
        and not (result["offer"] and not result["cta"])
    ):
        result["title"] = p["subject"] + "，从这件小事开始"
    return p, result


def recommendations(profile, history):
    today = dt.date.today()
    week = today.isocalendar()
    key = f"{week.year}-W{week.week:02d}"
    sc = scene_for("", profile)
    subject = profile.get("product") or (sc[1] if sc != FALLBACK else "店里的招牌")
    season = ["冬日", "春日", "夏日", "秋日"][(today.month % 12) // 3]
    entries = [
        (
            f"{season}里的一次碰面",
            "季节灵感",
            f"围绕{subject}，把{season}的相聚写成一句邀请。",
            "sun",
        ),
        (
            "把周末留给老朋友",
            "周末营销",
            f"为{subject}策划周末到店内容，面向结伴出行的朋友。",
            "calendar",
        ),
        (
            "给第一次来的顾客",
            "新客指南",
            f"为第一次了解{subject}的顾客做一份自然、亲切的介绍。",
            "spark",
        ),
    ]
    if sc[1] == "火锅":
        entries = [
            (
                season + "围炉，把朋友叫齐",
                "季节灵感",
                f"从{season}围桌聊天的瞬间宣传{subject}，邀请{profile.get('audience') or '朋友'}相聚。",
                "sun",
            ),
            (
                "今晚谁来下第一筷？",
                "聚餐邀约",
                f"用一个选菜问题为{subject}写一条朋友间的组局邀请。",
                "calendar",
            ),
            (
                "第一次涮，从哪一口开始",
                "新客指南",
                f"为初次来吃{subject}的人设计一次轻松的点菜对话。",
                "spark",
            ),
        ]
    elif sc[1] != "门店":
        entries[0] = (f"{season}里的{subject[:10]}", "季节灵感", entries[0][2], "sun")
        entries[2] = (
            f"第一次来，怎样选{subject[:8]}",
            "新客指南",
            entries[2][2],
            "spark",
        )
    rotation = (week.week + uidnum(subject)) % 3
    entries = entries[rotation:] + entries[:rotation]
    entries.sort(
        key=lambda e: (
            sum(e[0] in h.get("original", "") for h in history),
            -sum(h.get("preferredTag") == e[1] for h in history),
        )
    )
    return [
        dict(
            id=f"{key}-{e[3]}",
            title=e[0],
            tag=e[1],
            brief=e[0] + "。" + e[2],
            icon=e[3],
            week=key,
            basis="按本周日历与北半球季节推算，结合商家档案选题。",
        )
        for e in entries
    ]
