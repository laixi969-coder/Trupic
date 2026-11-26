"""Trupic adapter for the bundled hiccai-wenan writing and review skill."""

import re
from pathlib import Path
from .campaign import LOCKED

ROOT = Path(__file__).resolve().parents[1] / ".agents/skills/hiccai-wenan"
DOCUMENT = (ROOT / "SKILL.md").read_text(encoding="utf-8")
VERSION = re.search(r"^  version: ([\d.]+)$", DOCUMENT, re.M)[1]
CORE = DOCUMENT.split("---", 2)[2].strip()
FORMATS = dict(
    re.findall(
        r"^## (.+?)\n(.*?)(?=^## |\Z)",
        (ROOT / "references/formats.md").read_text(encoding="utf-8"),
        re.M | re.S,
    )
)
AWARDS = (ROOT / "references/creative-review.md").read_text(encoding="utf-8")


POSTER_HEADINGS = (
    "海报采用多层级闭环文案：一级 title 为主标题（8–18 字，具备真社交货币，把商品真实特性写进人与人之间的对话、嘴替或动作里，让人想拍照转发给某个人）；"
    "二级 body 为副标题（最多 20 字，用真实商品名、卖点细节或已确认价格接住主标题）；"
    "三级 cta 为行动收口（按顾客当前场景补一条已知时间、地点、挑选动作或唯一自然的下一步，形成转化闭环，无新信息可留空）；"
    "可选四级 socialPost 为直接可发朋友圈/小红书的配发正文（60–140 字口语表达，含开场钩子+卖点实证+评论区接话口子+自然收口）。"
    "不重复已单列的价格与条件。标点、数字、字母各计一字，空白不计。商家指定的标题逐字保留。"
)

SOCIAL_CURRENCY_CLOSED_LOOP = (
    "【hiccai-wenan v4.4.0 社交货币 × 商业闭环核心铁律】"
    "① 禁止单向商家广播句：凡是站在老板口吻喊顾客购买的平淡口号（如“下班路过带一盒”“新鲜直达等你来”“周末特惠别错过”“品质有底气”“鲜甜多汁不踩雷”）均不具备社交货币，一律重写；"
    "② 真社交货币（嘴替/双关/两人动作）：从当前商品的一条真实特性出发，把它放进两个人之间立刻能发生的对话、玩笑、分工或心照不宣的动作里（借鉴水果摊「比初恋还甜」让伴侣反问「哪一任」、可撕电影票「电影看同一场，散场后一人留半张」的底层机制，但必须从眼前商品重新发明，严禁套用「初恋」模板）；"
    "③ 假社交退稿检验：心里演一次顾客拍图发给谁（shareTo）和对方怎么接话（reply）——如果对方只能客套回“这广告写得真好 / 看着不错 / 在哪买”，或者拿掉该商品特点后句子依然成立，立即判为假社交并重写；删去“快转发/@好友”后句子本身仍值得转发；"
    "④ 商业行动闭环：主标题只负责让人想拍、想转、想接话；副标题用真实商品名、产地/工艺细节与已确认价格接住主标题；三级 cta 和四级 socialPost 立足顾客站的位置（街上/社区群/货架前/转发单图）给出自然且已确认的下一步，绝不替商家编造私信接单、预留、免单试吃等未确认服务。"
)


def poster_length_error(title, subtitle, locked):
    if not locked and not 8 <= len("".join(title.split())) <= 18:
        return "海报主标题需要 8–18 字"
    if len("".join(subtitle.split())) > 20:
        return "海报副标题最多 20 字"
    return ""


AI_CLICHE = re.compile(
    r"匠心打造|震撼来袭|重磅来袭|不容错过|极致体验|重新定义|引领潮流|开启.{0,8}之旅|解锁.{0,8}新体验|绝绝子|天花板|闭眼冲|颜值爆表|治愈瞬间|精彩呈现"
)

BROADCAST_CLICHE = re.compile(
    r"下班路过(?:带|买)|等你来(?:挑|选|抢|尝)|欢迎进店|欢迎选购|品质有底气|好物推荐|超值特惠|限时特惠|别错过|错过再等"
)


def cliche_error(text, brief=""):
    """Deterministic 0ms AI-slop guard (PRD §6). Never blocks phrases explicitly in brief."""
    for match in AI_CLICHE.finditer(text or ""):
        phrase = match.group(0)
        if phrase not in (brief or ""):
            return f"避免空泛AI套话「{phrase}」，请用具体画面、动作或真实卖点表达"
    return ""


def broadcast_error(title, brief=""):
    """Deterministic guard rejecting 1-way merchant broadcast headlines that lack social currency."""
    for match in BROADCAST_CLICHE.finditer(title or ""):
        phrase = match.group(0)
        if phrase not in (brief or ""):
            return f"主标题「{phrase}」偏单向商家叫卖，请改写成顾客想拍给朋友看、对方能接话的一句话"
    return ""


SHARING = "社交货币与自发传播"
ACTION_CLOSING = "商业文案的行动收口"
CLOSING = (
    ROOT.parent / "trupic-commercial-poster/references/closing-copy.md"
).read_text(encoding="utf-8")

ACTION_TYPES = (
    ("询问", r"询问|问问|咨询|问价|留资|问档期"),
    ("下单", r"下单|购买|订购|买单|补购|复购"),
    ("预约", r"预约|预订|报名|约个时间|约时间|约看"),
    ("到店", r"到店|进店|来店|到场|逛店"),
)


def conversion(plan):
    """Compile one grounded next step from the brief, before copy is written."""
    brief = plan["original"]
    if (
        no_cta(plan)
        or spec_line(plan)
        or re.search("只(?:要|写|给|列)(?:商品)?(?:规格|参数|交易条件|事实)", brief)
    ):
        return {}
    # A requested ending takes precedence over incidental actions earlier in the brief.
    parts = re.split("[，,。；;！？\n]", brief)
    positive = [
        p
        for p in parts
        if not re.search("不要|别写|禁止|不可|不支持|没有|仅作示例|假设", p)
    ]
    explicit = [
        p
        for p in positive
        if re.search("收口|引导|目标|希望|结尾|目的是|最后|让顾客", p)
    ]
    goal = next(
        (
            g
            for p in [*reversed(explicit), *reversed(positive)]
            for g, pattern in ACTION_TYPES
            if re.search(pattern, p)
        ),
        "",
    )
    if not goal or any(
        re.search(r"(?:不要|禁止|不支持|不能|不可)(?:引导|写|让顾客)?" + goal, p)
        for p in parts
    ):
        return {}
    sources = "。".join(
        [brief, plan.get("facts", ""), plan["profile"].get("facts", "")]
    )
    available = [
        p
        for p in re.split("[，,。；;！？\n]", sources)
        if not re.search(
            "没有|不要|不用|未开|不支持|禁止|不可|尚无|待定|假设|未确认|尚未|未提供|不开通",
            p,
        )
    ]
    channels = (
        ("小程序", "商品页", "网店", "购物车")
        if goal == "下单"
        else ("私信", "电话", "小程序")
    )
    channel = next(
        (
            c
            for p in [*reversed(explicit), *available]
            for c in channels
            if c in p and any(c in a for a in available)
        ),
        "",
    )
    return {"goal": goal, "channel": channel}


def factual_only(brief):
    return bool(
        re.search(
            r"只(?:需|要|写|给|列)(?:商品)?(?:规格|参数|交易条件|事实)|(?:促销|优惠|特价)(?:通知|消息|短信)|不要(?:分享|传播|社交)(?:话术|梗|创意)",
            brief,
        )
    )


POSTER_CREATIVE_BRIEF = (
    "这份需求是创作素材。名称、票价和限制条件是事实，可以放到副标题或三级标题。"
    "主标题要写出一句顾客看了想拍下来发给伴侣、朋友、家人或群聊的话（真社交货币）："
    "把商品的一个真实特性写进两个人之间的对话、嘴替、小分工或生活反差里，让对方看到能自然接话或约行动。"
    "每组换一个社交切口；片名/品名加价格、单向商家叫卖（如“下班路过买一盒”“周末特惠等你来”）、调换词序、加上泛用赞词都不算合格标题。"
    "用一句能单独念出口、像朋友聊天的话完成这个想法，避免以‘治愈瞬间、精彩呈现’一类评价收尾。"
    "有原图时只使用能看见的细节，不推测剧情、角色经历或效果。"
    "价格保留原来的写法。名称与价格在20字内能说清时放在一行，省掉重复评价。"
    "三级标题按顾客所处位置落一个自然且已确认的下一步；没有另外的必要条件或指定行动时可留空。"
)


def wants_creative_headline(brief):
    return not (
        LOCKED.search(brief) or factual_only(brief)
        or re.search(r"只(?:报|写|标|要)价格|(?:原文|原话|原标题)(?:照用|不改|保留)|"
                     r"(?:照抄|照用|沿用|保留)(?:原文|原话|原标题)|(?:片名|品名|商品名|价格)(?:作为|当作|用作|做|作|为)主标题", brief)
    )


def copied_headline(title, brief):
    # Ignore punctuation so adding book-title marks doesn't turn a name into a new headline.
    headline = re.sub(r"\W+", "", title).casefold()
    return bool(headline and headline in re.sub(r"\W+", "", brief).casefold())


def social_headline(plan):
    brief = plan["original"]
    return (
        (not plan.get("autoCreation") or bool(re.search("朋友圈|转发|社交|分享给|小红书", brief)))
        and not LOCKED.search(brief)
        and not factual_only(brief)
        and plan.get("goal") != "分享实用知识"
        and not re.search(
            r"只(?:报|写|标|要)价格|只讲卖点|不要玩梗|不要(?:创意|噱头)|(?:直接|如实)列出",
            brief,
        )
    )


def wants_social_currency(plan):
    """True for commercial creative briefs that should carry hiccai-wenan v4.4.0 social currency."""
    brief = plan["original"]
    return (
        not LOCKED.search(brief)
        and not factual_only(brief)
        and plan.get("goal") != "分享实用知识"
        and not re.search(
            r"只(?:报|写|标|要)价格|只讲卖点|不要玩梗|不要(?:创意|噱头)|(?:直接|如实)列出",
            brief,
        )
    )


HEADLINE_BRIEF = (
    "把社交货币放在主标题 title。先构思三个真正不同的社交切口：① 关系嘴替（替顾客向伴侣/闺蜜/同事说出带点俏皮或体贴的话，把商品特点和人际关系双关到一起）；"
    "② 两人动作与分工（把商品的真实卖点放进两个人一起吃/挑/分享/互相打趣的具体动作里）；③ 实在生活观察（让人忍不住拍图吐槽或私下安利给朋友的一句真话）。"
    "只读标题和看得到的商品，顾客就能懂，还能立刻想起一个想发给的人。"
    "取商家已确认的一条卖点，问它改变了谁在哪一刻的什么感受。去掉卖点后情绪照样成立、或换掉商品还能原句照搬，都要重写。"
    "心里试一次：对方会回一句什么有来有回的话？如果对方只能回“广告不错/看着好吃/在哪买”，说明没有社交货币，必须重写。"
    "避免单向叫卖、索要转发、套用初恋句式、虚构顾客评价或未确认承诺。"
)


def spec_line(plan):
    brief = plan["original"]
    if plan.get("kind") != "copy" or not re.search(
        r"只(?:需|要|写|给|列)(?:商品)?(?:规格|参数)", brief
    ):
        return ""
    # Only use an explicitly supplied specification; never guess missing fields.
    match = re.search(
        r"(?:请写明|规格[：:]|参数[：:]|请列出)(.+?)(?=[，,](?:只|请|不要)|[。；;\n]|$)",
        brief,
    )
    return match.group(1).strip() if match else ""


def sections(plan):
    brief = plan["original"]
    media = {
        "poster": "广告语、海报、系列",
        "video": "短视频、品牌片、声音广告",
        "copy": "小红书、朋友圈和社媒",
    }
    chosen = [media.get(plan.get("kind"), media["copy"])]
    if social_headline(plan) or wants_social_currency(plan):
        chosen.append(SHARING)
    if (conversion(plan) or plan.get("kind") == "poster") and ACTION_CLOSING in FORMATS and not no_cta(plan):
        chosen.append(ACTION_CLOSING)
    if conversion(plan):
        chosen.append("卖货任务：让创意推动决策")
    for pattern, title in (
        ("商品主图|详情页|电商首屏", "商品主图与详情页逐屏"),
        ("小红书|朋友圈|群聊", "小红书、朋友圈和社媒"),
        ("借势|热点|热梗", "热点与梗"),
        ("促销|打折|优惠|满减|销售|招商", "销售页、促销、招商"),
        ("咨询|预约|留资|约个时间|约时间|约看", "咨询与留资"),
        ("客户案例", "客户案例"),
        ("高端|奢侈|奢品|豪宅|样板间|看房", "高端、奢侈品、地产"),
        ("卖货|转化|促销|直播|电商|私域|招商|预约|优惠", "卖货任务：让创意推动决策"),
    ):
        if re.search(pattern, brief):
            chosen.append(title)
    return list(dict.fromkeys(chosen))


def instructions(plan):
    text = (
        CORE + "\n" + "\n".join("## " + s + "\n" + FORMATS[s] for s in sections(plan))
    )
    if social_headline(plan) or wants_social_currency(plan):
        text += "\n" + HEADLINE_BRIEF
    if conversion(plan):
        text += "\n" + CLOSING
    if re.search("冲奖|广告大奖|获奖级", plan["original"]):
        text += "\n" + AWARDS
    return text


def no_cta(plan):
    return bool(
        re.search(
            "不要(?:加|写)?(?:CTA|行动号召|行动引导)|不加CTA|无需CTA|只(?:写|要|给)(?:一句)?(?:主标题|标题|广告语)",
            plan["original"],
            re.I,
        )
    )


def record(plan, mode):
    record = dict(name="hiccai-wenan", version=VERSION, mode=mode, sections=sections(plan))
    if plan.get("kind") == "poster":
        record["posterHeadings"] = True
    return record
