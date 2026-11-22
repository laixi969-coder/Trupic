"""Merchant-grounded copy directions and the timed lines delivered in a Trupic film."""

import json
import re

from .design import RULES

ROUTES = json.loads(RULES.with_name("copy-directions.json").read_text())
BENEFITS = json.loads(RULES.with_name("benefit-scenes.json").read_text())
UNSUPPORTED = re.compile(
    "不支持|不能|不可|不具备|不带|无法|并非|没有|暂不|不提供|无此|不含|别提|不要|不提|禁止|避免|未经|未确认|待确认|待核实|待定|尚未|没确认|是否|假设|比如|例如|参考|竞品|对手|别家|希望能|能否|可能|据说|如果|尚无|未核实|仅限|仅部分|部分型号|仅高配|选装|能不能|可不可以|竞对|友商|待查|暂未|不确定|不清楚|未知"
)


def evidence_clauses(plan):
    sources = (
        plan["original"],
        plan.get("facts", ""),
        plan["profile"].get("facts", ""),
    )
    positive, excluded = [], []
    for source in sources:
        # Keep comma-delimited caveats with the feature they qualify.
        for sentence in re.findall(r"[^。；;！？?\n]+[！？?]?", source):
            if UNSUPPORTED.search(sentence) or sentence.rstrip().endswith(
                ("？", "?", "吗")
            ):
                excluded.append(sentence)
            else:
                positive.append(sentence)
    return positive, excluded


def confirmed_feature(feature, subject, positive, excluded):
    if any(re.search(subject, sentence) for sentence in excluded):
        return None
    return next(
        (m.group() for sentence in positive if (m := re.search(feature, sentence))),
        None,
    )


def benefit_scene(plan, row):
    if not row:
        return None
    positive, excluded = evidence_clauses(plan)
    situation = "。".join([*positive, plan.get("audience", "")])
    for rule in BENEFITS:
        if row["product"] not in rule["products"]:
            continue
        feature = confirmed_feature(
            rule["feature"], rule["subject"], positive, excluded
        )
        if feature:
            scene = next(
                s
                for s in rule["scenes"]
                if not s.get("when") or re.search(s["when"], situation)
            )
            return {**scene, "evidence": feature}
    return None


LOCKED = re.compile(
    r'(?:主标题|标题)(?:写成|定为|用|是|为)?[：:\s]*[「“"]([^」”"]{1,40})[」”"]'
)
NUMBER = r"\d+(?:\.\d+)?"
COUNT = r"[一二两三四五六七八九十0-9]+"
OFFER = re.compile(
    rf"(?:满|每满)\s*{NUMBER}(?:元|件|杯)?\s*(?:立减|减)\s*{NUMBER}(?:元)?"
    rf"|(?:满|任选){COUNT}(?:件|杯|份)\s*(?:享|打)?\s*{NUMBER}折"
    rf"|第{COUNT}(?:件|杯|份)(?:半价|(?:享|打)?{NUMBER}折)"
    rf"|买{COUNT}[赠送]{COUNT}|(?:立省|优惠|折扣)\s*{NUMBER}\s*[%％]"
    rf"|(?:每[杯份位人]|会员专享|会员价|低至|最低|最高|售价|优惠价|活动价|原价|现价|折后价|首单)?\s*{NUMBER}\s*(?:元|折)(?:起)?(?:\s*[/／]\s*(?:杯|份|位|人|件|套|瓶|单))?(?:起)?"
)
SPECIFICATION = re.compile(
    rf"(?:约|最高|最长|最低)?(?:续航|净含量|容量|重量|杯容|轴距|口径|直径)(?:约为|最长约|最高约|可达|约|最长|最高|为)?\s*{NUMBER}\s*(?:小时|分钟|毫升|升|毫米|厘米|公斤|千克|克|ml|mm|kg|cm|g)",
    re.I,
)


def quoted_specs(plan):
    facts = "。".join(
        (plan["original"], plan.get("facts", ""), plan["profile"].get("facts", ""))
    )
    return [
        m.group()
        for clause in re.split("[，。；;！?？\n]", facts)
        if not re.search("不要|禁止|待定|未确认|不提|是否|未知|假设|比如|例如", clause)
        for m in SPECIFICATION.finditer(clause)
    ]


SIGNALS = (
    ("耳罩可拆洗", "耳罩脏了？拆下来洗", "耳罩可拆洗。"),
    ("可拆洗耳罩", "耳罩脏了？拆下来洗", "可拆洗耳罩。"),
    ("可折叠", "用时展开，收时折起", "可折叠。"),
    ("一键开盖", "一按，盖就开", "一键开盖。"),
    ("可进洗碗机", "喝完，交给洗碗机", "可进洗碗机。"),
)
DECLARED = re.compile(
    r"(?:确认信息|已确认|商品特点|卖点|实物特点)[：:]\s*([^。；;\n]{2,70})"
)


def copy_route(plan):
    for source in (
        plan["original"],
        plan["profile"].get("product", ""),
        plan["subject"],
    ):
        for row in ROUTES:
            if re.search(row["match"], source, re.I):
                return row
    return None


def copy_angle(plan, index, use_social=False):
    row = copy_route(plan)
    if not row:
        explicit = DECLARED.search(plan["original"])
        evidence = (plan.get("facts") or (explicit.group(1) if explicit else "")).strip(
            " ，。"
        )
        first = re.split("[，。；]", evidence)[0]
        if 3 <= len(first) <= 20:
            product = plan["profile"].get("product") or plan["subject"]
            titles = (first, product + "怎么挑？", "挑" + product + "，看这个细节")
            return dict(
                title=titles[index],
                body=evidence,
                cta="查看商品详情。",
                detailLine=first,
            )
        return {}
    title, body = row["routes"][index]
    if use_social:
        style = row
        words = {}
        if scene := row.get("socialScene"):
            sources = "。".join(
                (
                    plan["original"],
                    plan.get("facts", ""),
                    plan["profile"].get("facts", ""),
                )
            )
            for clause in re.split(r"[。！？，；,;\n]", sources):
                if re.search(
                    "不要|不提|不含|没有|没刻度|无刻度|不带|不陪|不想|未确认|假设|如果|是否|别写|避免",
                    clause,
                ):
                    continue
                if match := re.search(scene["match"], clause):
                    style = scene
                    words = match.groupdict()
                    break
        options = [line.format(**words) for line in style["socialTitles"]]
        recent = plan.get("recent", [])
        # Keep the chosen creative angle when possible, then try the next unused line.
        choice = index
        if options[index] in recent:
            for offset in range(1, len(options)):
                other = (index + offset) % len(options)
                if options[other] not in recent:
                    choice = other
                    break
        title = options[choice]
        body = (
            style["socialBodies"][choice].format(**words)
            if "socialBodies" in style
            else row["routes"][choice][1]
        )
    brief = plan["original"]
    known = "。".join((brief, plan.get("facts", ""), plan["profile"].get("facts", "")))
    reveal = row["reveal"]
    cta = row["cta"]
    if index == 0:
        positive, excluded = evidence_clauses(plan)
        for signal, headline, line in SIGNALS:
            if confirmed_feature(
                signal, signal.replace("可", ".{0,4}"), positive, excluded
            ):
                title, body, reveal = headline, line, line
                break
    if not use_social and row["latin"] == "MATCHA" and "午休" in brief and index == 0:
        title = "午休这杯，先别搅"
    if row["latin"] == "BREAK" and "学生" in (brief + plan["audience"]) and index == 0:
        title = "下课铃一响，谁还敢说没空打球？" if use_social else "下课铃响，轮到开球"
        body = "把课表合上，喊上想一起打球的人。先到球桌的那个，来开第一杆。"
    if row["latin"] == "SCENT" and "试香" in brief:
        cta = "到店，亲自闻一闻。"
    if row["latin"] == "MARKET" and not OFFER.search(known):
        reveal = "清单上要买什么？从那一站开逛。"
    if row["latin"] == "MATCHA" and "分层" not in known:
        reveal = "下一口，试试把茶和奶搅匀。"
    if plan.get("kind") == "video" and title == "耳罩脏了？拆下来洗":
        title = "耳罩脏了，怎么办？"
    benefit = benefit_scene(plan, row) if use_social else None
    if benefit:
        options = benefit["titles"]
        order = options[index:] + options[:index]
        title = next(
            (line for line in order if line not in plan.get("recent", [])), order[0]
        )
        body = reveal = benefit["evidence"] + "。"
    specs = quoted_specs(plan)
    return dict(
        title=title, body=body, cta=cta, detailLine=specs[0] if specs else reveal
    )


def offer_and_terms(plan, conditions):
    known = "。".join(
        (plan["original"], plan.get("facts", ""), plan["profile"].get("facts", ""))
    )
    prices = dict.fromkeys(x.group().strip() for x in OFFER.finditer(known))
    return "，".join(prices), conditions(known)


def complete_body(plan, body, offer, terms):
    details = [plan.get("facts", ""), plan["profile"].get("facts", "")]
    found = DECLARED.search(plan["original"])
    if found:
        details.insert(0, found.group(1))
    # Append confirmed facts and conditions after any stylistic shortening.
    lines = [body.strip()]
    for item in (*details, *quoted_specs(plan), offer, terms):
        value = item.strip(" ，。；")
        if value and value not in "。".join(lines):
            lines.append(value)
    return "".join(
        line if line.endswith(("。", "？", "！", "?", "!")) else line + "。"
        for line in lines
        if line
    )


def storyboard(plan, copy):
    row = copy_route(plan) or {}
    line = copy.get("detailLine") or row.get("reveal") or copy["body"].split("。")[0]
    if line.rstrip("。！？") == copy["title"].rstrip("。！？"):
        line = next(
            (
                part
                for part in re.split("[。！？]", copy["body"])
                if part and part != line.rstrip("。！？")
            ),
            plan["subject"],
        )
    return [
        dict(start=0, end=3, camera="近景切入", line=copy["title"], caption=""),
        dict(start=3, end=6, camera="推进细节", line=line, caption=""),
        dict(
            start=6,
            end=9,
            camera="全景收束",
            line=copy["cta"] or plan["profile"].get("name") or copy["title"],
            caption=" · ".join(filter(None, (copy.get("offer"), copy.get("terms")))),
        ),
    ]
