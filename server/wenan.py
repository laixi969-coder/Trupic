"""Trupic adapter for the bundled hiccai-wenan writing and review skill."""

import re
from pathlib import Path
from .campaign import LOCKED, benefit_scene, complete_body, copy_route, quoted_specs

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


SHARING = "社交货币与自发传播"
CLOSING = (
    ROOT.parent / "trupic-commercial-poster/references/closing-copy.md"
).read_text(encoding="utf-8")

ACTION_TYPES = (
    ("询问", r"询问|问问|咨询|问价|留资|问档期"),
    ("下单", r"下单|购买|订购|买单|补购|复购"),
    ("预约", r"预约|预订|报名|约个时间|约时间|约看"),
    ("到店", r"到店|进店|来店|到场|逛店"),
)


def conversion(plan, product=""):
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
    row = copy_route(plan) or {}
    prod = (
        product
        or plan.get("promptBrief", {}).get("reading", {}).get("product")
        or plan["profile"].get("product")
        or row.get("product")
        or plan["subject"]
    )
    if prod == "衣物洗涤" and row:
        matched = re.search(row["match"], brief)
        prod = matched.group() if matched else prod
    brand = plan["profile"].get("name") or ""
    if not goal and (factual_only(brief) or plan.get("goal") == "分享实用知识"):
        return {}
    if not goal:
        goal = (
            "预约"
            if row.get("latin") == "DRIVE"
            else "到店"
            if re.search(
                "门店|百货|商场|到店|开店|线下|球房|台球室|水果店", " ".join(positive)
            )
            else "下单"
            if re.search("商品页|购物车|电商详情|网店", " ".join(positive))
            else "询问"
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
    drive = row.get("latin") == "DRIVE"
    when = "周末" if "周末" in " ".join(positive) else ""
    if goal == "下单":
        entry = "在" + channel if channel else ""
        line = f"{entry}下单这款{prod}。"
        if (
            row.get("latin") == "WASH"
            and "液" in prod
            and re.search("补购|补货|补一瓶|复购", brief)
        ):
            line = f"家里那瓶见底时，{entry}补一瓶{prod}。"
    elif goal in ("询问", "预约"):
        entry = {"电话": "来电", "小程序": "在小程序里"}.get(channel, channel)
        if drive:
            line = (
                f"{entry}问问{when}哪天能试驾。"
                if goal == "询问"
                else f"{entry}预约{when}试驾。"
            )
        elif goal == "预约":
            line = f"{entry}预约{prod}，说说你方便的时间。"
        else:
            topic = next(
                (
                    q
                    for pat, q in (
                        ("库存|有货", "现在有没有货"),
                        ("价格|报价|问价", "具体多少钱"),
                        ("用量|倒多少", "每次该用多少"),
                        ("尺寸|尺码", "怎么选尺寸"),
                    )
                    if re.search(pat, "。".join(positive))
                ),
                "",
            )
            topic = topic or (
                "每次该倒多少" if row.get("latin") == "WASH" else "怎么选"
            )
            line = f"{entry}问问{prod}{topic}。"
    else:
        store = "来" + brand if brand else "到店"
        item = (
            re.search(row["socialScene"]["match"], "。".join(positive))
            if row.get("latin") == "MARKET"
            else None
        )
        if item:
            line = f"{when}{store}，先把{item['item']}买上。"
        elif drive:
            line = f"{when}{store}，坐进驾驶位试试。"
        else:
            line = (
                f"{when}{store}逛逛。"
                if row.get("latin") == "MARKET"
                else f"{when}{store}看看{prod}。"
            )
        channel = ""
    return {"goal": goal, "channel": channel, "line": line}


def factual_only(brief):
    return bool(
        re.search(
            r"只(?:需|要|写|给|列)(?:商品)?(?:规格|参数|交易条件|事实)|(?:促销|优惠|特价)(?:通知|消息|短信)|不要(?:分享|传播|社交)(?:话术|梗|创意)",
            brief,
        )
    )


def social_headline(plan):
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
    "把社交货币放在主标题 title。先各写一个不同切口：一句顾客想借用的心里话、"
    "一个一眼认得的生活矛盾、一个同行愿意传给同行的发现。选最适合这件商品和品牌语气的一句。"
    "只读标题和看得到的商品，顾客就能懂，还能想起一个想发给的人。"
    "取商家已确认的一条卖点，问它改变了谁在哪一刻的什么感受。用那个动作把卖点和情绪写进同一句。想象转给谁、替他说出什么。资料不足就从实际用途取材，不能虚构专有功能。去掉卖点后情绪照样成立、或换掉商品还能原句照搬，都要重写。"
    "心里试一次：对方怎么接这句话？说不清就重写。只交付胜出的标题，正文承接它，短片首镜用它。"
    "避免索要转发、套用初恋句式、虚构顾客评价或产品承诺。"
)


def social_brief(plan):
    brief = HEADLINE_BRIEF
    scene = benefit_scene(plan, copy_route(plan))
    if scene:
        brief += f" 可用卖点「{scene['evidence']}」。可探索的情绪是「{scene['emotion']}」，分享动机是「{scene['share']}」。"
    return brief


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
    if social_headline(plan):
        chosen.append(SHARING)
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
    if social_headline(plan):
        text += "\n" + social_brief(plan)
    if not no_cta(plan) and not factual_only(plan["original"]):
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
    return dict(
        name="hiccai-wenan", version=VERSION, mode=mode, sections=sections(plan)
    )


def apply_local(plan, draft):
    """Implement the direct-notice and explicit opt-out rules without inference."""
    brief = plan["original"]
    specs = quoted_specs(plan)
    if specs and re.search("选购|对比|比较|商品主图|商品参数|详情页", brief):
        # A shopping comparison needs the actual specification and its qualifiers.
        if plan.get("kind") == "video":
            draft["detailLine"] = specs[0]
        else:
            draft["body"] = complete_body(
                plan, "，".join(dict.fromkeys(specs)), draft["offer"], draft["terms"]
            )
    action = conversion(plan)
    if action:
        draft["cta"] = action["line"]
    if no_cta(plan):
        draft["cta"] = ""
    if (
        plan.get("kind") == "copy"
        and draft["offer"]
        and re.search("促销(?:消息|通知|短信)|特价通知|优惠通知", brief)
    ):
        # Preserve quantity, validity and eligibility together. Only use whole factual clauses.
        clauses = [s.strip() for s in re.split("[，。；！？\\n]", brief)]
        facts = [
            s
            for s in clauses
            if 0 < len(s) <= 48
            and not re.search(
                "帮我|请写|写一|不要|不超过|标题|文案|通知|消息|字以内|海报", s
            )
            and re.search("元|折|截止|有效|全店|仅限|无需|每人|不可叠加|限购|适用", s)
        ]
        # A limit such as “外送除外” can be a whole clause of its own.
        # Retain short factual qualifiers adjacent to the offer before the writing brief.
        if facts and draft["offer"] in facts[0]:
            position = clauses.index(facts[0])
            lead = facts[0]
            preceding = [s for s in clauses[:position] if s in facts]
            facts = [lead, *preceding]
            for clause in clauses[position + 1 :]:
                if re.search(
                    "请|帮我|写|生成|文案|通知|消息|只给|不要CTA|不超过.{0,4}字", clause
                ):
                    break
                if clause:
                    facts.append(clause)

            if not LOCKED.search(brief):
                draft["title"] = facts[0]
                body = "，".join(facts[1:])
            else:
                body = "，".join(facts)
            draft["body"] = complete_body(
                plan, body, "", draft["terms"] if draft["terms"] not in body else ""
            )
            draft["cta"] = action.get("line", "")
    if line := spec_line(plan):
        draft.update(title=line, body="", cta="")
    draft["writingSkill"] = record(plan, "本地规则")
    return draft
