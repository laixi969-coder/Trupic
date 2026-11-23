"""Creative planning, licensed reference methods, and grounded copy generation."""

import datetime as dt
import hashlib
import json
import re

from . import model, wenan
from .campaign import (
    LOCKED,
    complete_body,
    offer_and_terms,
)
from .design import direction

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
# Visual categories supply a subject and camera cue for layout.
SCENES = [
    ('台球|桌球|球房', '台球', '撞球的一瞬'),
    ('火锅|锅底|涮肉|聚餐', '火锅', '围桌的距离'),
    ('抹茶|奶茶|茶饮|咖啡|柑橘|饮品|果茶|饮料', '饮品', '手边的一杯'),
    ('面包|可颂|烘焙|甜品|蛋糕', '烘焙', '清晨的第一口'),
    ('美容|护肤|美甲|护理|美发', '日常护理', '日常的一刻'),
    ('花店|花束|鲜花|花艺', '花艺', '挑选花束的瞬间'),
    ('书店|图书|阅读', '阅读', '翻开一页'),
    ('服装|穿搭|衣服|穿搭', '穿搭', '出门前的搭配'),
    ('健身|瑜伽|运动', '运动', '出发前一刻'),
]
FALLBACK = ("", "门店", "日常的发现")
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
            {
                "auto": "看见车身的线条",
                "commerce": "靠近，看见细节",
                "clean": "从一件日常小事开始",
                "home": "触摸日常的纹理",
                "retail": "走进今天的好发现",
                "beauty": "看见光落在瓶身",
            }.get(sector, sc[2]),
        )
    goal = next(
        (
            label
            for pattern, label in [
                ("新客|第一次|首次到店|初次体验", "邀请新客进店"),
                ("复购|回购|老客|回头客|再次到店", "邀请老客再次到店"),
                ("知识|科普", "分享实用知识"),
                ("预订|预约", "引导咨询预约"),
                ("上新|新品", "介绍新商品"),
                ("朋友|聚餐|组局", "邀请朋友相聚"),
            ]
            if re.search(pattern, brief)
        ),
        "介绍商品或活动",
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
        briefGoal=goal,
        audience=audience,
        subject=sc[1],
        reference=match["method"],
        referenceId=match["id"],
        shot=sc[2],
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


def copy_inputs(plan):
    """Quote metadata and merchant-specified text, before a model writes any copy."""
    locked = LOCKED.search(plan["original"])
    offer, terms = offer_and_terms(plan, promotion_terms)
    return dict(title=locked.group(1) if locked else "", body="", cta="", detailLine="",
                offer=offer, terms=terms, angle=plan["angle"], method=plan["method"],
                shot=plan["shot"], engine="", review="")


def draft_copy(plan, variant=0):
    """Prepare a factual preview for older quote and internal preview callers."""
    draft = copy_inputs(plan)
    draft["title"] = draft["title"] or plan["profile"].get("product") or plan["subject"]
    draft["body"] = complete_body(plan, "", draft["offer"], draft["terms"])
    draft["detailLine"] = draft["body"]
    draft["engine"] = "商家资料预览"
    return draft


def unconfirmed_number(content, known):
    def claims(text):
        return {re.sub(r"\s+", "", match) for match in NUMCLAIM.findall(text)}

    return bool(claims(content) - claims(known))


def unsupported_copy(content, known):
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
    return (
        RISK.search(content)
        or unconfirmed_number(content, known)
        or any(x in content and x not in known for x in guarded)
    )


def generate_copy(plan, variant=0, *, revision_note=""):
    base = copy_inputs(plan)
    if not model.engine_name():
        raise ValueError("请在模型平台启用文字模型后生成文案。")
    spec = wenan.spec_line(plan)
    skill = wenan.instructions(plan)
    prompt = (
        skill
        + "\n按上述 Skill 和商家要求写成品。只返回 JSON 对象，含 title、body、cta、detailLine。cta 在无需行动引导时可为空。detailLine 为可选的短片中段字幕。目标篇幅按用户要求和当前交付尺寸。"
    )
    prompt += " 根据素材重新创作，标题不要照抄整句需求，明确指定的标题和规格须逐字保留。"
    poster = plan.get("kind") == "poster"
    locked = LOCKED.search(plan["original"])
    action = wenan.conversion(plan)
    if poster:
        prompt += wenan.POSTER_HEADINGS
    if not action and not poster:
        prompt += " 本次没有指定交易动作，cta 留空。片名和商品名是资料，除非用户明确指定标题，否则可以另写创意标题。"
    elif action and not action["channel"]:
        prompt += " 未提供渠道，不得写点击、私信、扫码或拨打电话。"
    if revision_note:
        prompt += " 上一稿需要重写：" + revision_note + "。围绕用户提供的主题重新写标题和正文，保留明确指定的字句和交易条件。不要复述创作需求。"
    if spec:
        prompt += " 本次只交一行已给定的规格，放入 title，body 与 cta 留空。"
    try:
        directions = plan.get("promptBrief", {}).get("prompts", {})
        val, engine = model.ask(
            prompt,
            {
                "plan": {k: plan[k] for k in ("original", "facts", "profile", "sourceReview", "goal", "kind") if k in plan},
                "writingBrief": directions.get("copy", ""),
                "filmBrief": directions.get("video", ""),
                "variation": variant,
            },
        )
        if poster and isinstance(val.get("title"), str) and isinstance(val.get("body"), str):
            if locked:
                val["title"] = locked.group(1)
            if error := wenan.poster_length_error(val["title"], val["body"], locked):
                return {**base, "reviewFlag": error}
        for k, maxlen in (("title", max(40 if locked else 30, len(spec))), ("body", 260), ("cta", 40)):
            if (
                not isinstance(val.get(k), str)
                or not (0 if k == "cta" or ((poster or spec) and k == "body") else 1)
                <= len(val[k].strip())
                <= maxlen
            ):
                return {**base, "reviewFlag": "模型草稿格式异常"}
        if (not spec and not LOCKED.search(plan["original"]) and not wenan.factual_only(plan["original"])
                and val["title"].strip() == plan["original"].strip()):
            return {**base, "reviewFlag": "标题复述了输入需求"}
        if spec and (
            val["title"].strip() != spec or val["body"].strip() or val["cta"].strip()
        ):
            return {**base, "reviewFlag": "模型草稿格式异常"}
        if not action and (not poster or wenan.no_cta(plan)):
            val["cta"] = ""
        detail = val.get("detailLine", "")
        if not isinstance(detail, str) or len(detail) > 32:
            return {**base, "reviewFlag": "模型草稿格式异常"}
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
        if unsupported_copy(content, known):
            return {**base, "reviewFlag": "模型草稿含未经确认的声明"}
        headline_review = (
            " 单独遮住正文和行动号召审主标题：第一眼读懂了吗，商品和这句话有什么关系？"
            "请在心里指出哪条已知卖点或产品用途让哪种顾客情绪成立；移除卖点后若同一句还成立，退稿。资料不足时只允许有根据的用途。核对目标受众与情绪是否相符。"
            "想象一个具体接收人和一句自然的接话。只有成立才返回 headlineOk 为 true。"
            "靠正文解释、换个商品照样成立、只催转发的标题都应退稿。"
            if wenan.social_headline(plan)
            else ""
        )
        action_review = (
            " 独立审末句，核对目标、与商品的关系、入口依据及动作是否唯一。通过时另返 closingOk 为 true。"
            if action
            else ""
        )
        review_prompt = (
            "核对草稿与商家明确要求、原始资料和原图观察。价格、片名、商品名和限制条件必须准确。"
            "图片中可见的细节和邀请式创意表达可以使用。只有出现具体事实错误、杜撰承诺或违反明确要求才退稿。"
            "行动引导可提出询问，不得编造预约或购买渠道。返回 JSON，ok 为布尔值，reason 简短写出依据。"
            + headline_review + action_review
        )
        review, _ = model.ask(
            review_prompt,
            {
                "source": known,
                "visual": plan["shot"],
                "上传图片可见内容": plan.get("sourceReview", {}).get("reason", ""),
                "goal": plan["goal"],
                "closing": action,
                "draft": val,
            },
            450,
        )
        if (
            review.get("ok") is not True
            or (headline_review and review.get("headlineOk") is not True)
        ):
            return {
                **base,
                "reviewFlag": "模型草稿复核未通过",
                "revisionNote": str(review.get("reason", ""))[:200],
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
            return {**base, "reviewFlag": "行动引导未通过复核",
                    "revisionNote": "请按照商家要求写一个可执行的行动，只使用已提供的渠道。"}
        body = val["body"].strip()
        if not poster and not spec:
            body = complete_body(plan, body, base["offer"], base["terms"])
        return {
            **base,
            "title": val["title"].strip(),
            "body": body,
            "cta": val["cta"].strip(),
            "detailLine": detail or base["detailLine"],
            "writingSkill": wenan.record(plan, "模型创作与复核"),
            "engine": engine,
            "review": str(review.get("reason", "已复核创意与经营事实。"))[:200],
        }
    except model.InvalidModelOutput:
        return {**base, "reviewFlag": "模型回复格式异常"}
    except Exception as exc:
        return {
            **base,
            "callError": model.copy_failure_message(exc),
            "reviewFlag": "模型调用未完成",
            "review": "模型未返回可用内容。",
        }


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
            recentUses=sum(e[0] in h.get("original", "") for h in history),
            relevance=f"结合{subject}与{profile.get('audience') or '目标顾客'}的{e[1]}。",
            basis="按本周日历与北半球季节推算，结合商家档案选题。",
        )
        for e in entries
    ]
