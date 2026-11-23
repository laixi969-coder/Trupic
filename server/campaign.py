"""Merchant-grounded copy directions and the timed lines delivered in a Trupic film."""

import json
import re

from .design import RULES
from .shot_detail import product_detail

ROUTES = json.loads(RULES.with_name("copy-directions.json").read_text())
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


def offer_and_terms(plan, conditions):
    known = "。".join(
        (plan["original"], plan.get("facts", ""), plan["profile"].get("facts", ""))
    )
    prices = dict.fromkeys(x.group().strip() for x in OFFER.finditer(known))
    return "，".join(prices), conditions(known)


def complete_body(plan, body, offer, terms):
    details = [plan.get("facts", ""), plan["profile"].get("facts", "")]
    if plan.get("autoCreation") and plan.get("facts", "").strip() == plan["original"].strip():
        # The one-line brief can include a price. Keep the separate offer and terms.
        details = [plan["profile"].get("facts", "")] if not re.search("仅|限|有效|起售|不与|不叠加|满减|每人|截止|会员|适用", plan["original"]) else details
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


def storyboard(plan, copy, asset=None):
    if plan.get("bundleRole"):
        line = re.split(r"[。；;\n]", copy["body"], maxsplit=1)[0]
    else:
        line = copy.get("detailLine") or copy["body"].split("。")[0]
        if line.rstrip("。！？") == copy["title"].rstrip("。！？"):
            line = next(
                (part for part in re.split("[。！？]", copy["body"])
                 if part and part != line.rstrip("。！？")),
                plan["subject"],
            )
    closing = copy.get("cta") or plan["profile"].get("name") or copy["title"]
    if not copy.get("cta") and closing == copy["title"] and plan.get("posterArt", {}).get("composition") == "material":
        closing = plan.get("promptBrief", {}).get("reading", {}).get("product") or closing
    if not copy.get("cta") and plan.get("posterArt", {}).get("optics"):
        product = plan["profile"].get("product", "").strip()
        closing = re.sub(r"\s*(?:相机机身|单反机身|机身)$", "", product).strip() or closing
    shots = [
        dict(start=0, end=3, camera="近景切入", line=copy["title"], caption=""),
        dict(start=3, end=6, camera="推进细节", line=line, caption=""),
        dict(
            start=6,
            end=9,
            camera="全景收束",
            line=closing,
            caption=" · ".join(filter(None, (copy.get("offer"), copy.get("terms")))),
        ),
    ]
    art = plan.get("posterArt") or {}
    if art.get("concept"):
        shots[0]["purpose"] = art["concept"]
        shots[2]["purpose"] = "退回完整外形并停住，让观众读完「" + closing + "」。"
    if evidence := product_detail(plan, asset):
        label = evidence["label"]
        shots[1].update(
            line=evidence.get("claim") or label,
            camera="原图慢推",
            evidence=evidence,
            purpose="从完整实拍画面缓慢推近。" if evidence["source"] == "完整原图" else f"先在「{label}」上停一拍，再向这处细节缓慢推近。",
        )
    elif plan.get("visualSource") == "concept":
        shots[1]["purpose"] = "以场景承接开场，字幕沿用文案里的信息。"
    duration = plan.get("output", {}).get("duration", 9)
    if duration == 15:
        shots[1]["end"] = shots[2]["start"] = 10
        shots[2]["end"] = 15
    elif duration in (30, 45):
        segments = [s.strip() for s in re.split(r"[。！？；;，,\n]", copy["body"]) if s.strip()]
        facts = list(dict.fromkeys([*plan.get("coordination", {}).get("facts", []), *segments]))
        used = {shot["line"].strip("。！？") for shot in shots}
        extras = [f for f in facts if f not in used and len(f) > 2]
        needed = 2 if duration == 30 else 4
        if len(extras) < needed:
            raise ValueError(f"制作 {duration} 秒短片需要 {needed} 条不同的商品卖点或使用场景，请补充。")
        middle = [dict(camera=camera, line=fact, caption="", purpose="呈现商家提供的具体信息。")
                  for camera, fact in zip(("侧面观察","场景说明","局部展示","使用提示"), extras[:needed])]
        shots[2:2] = middle
        cuts = [0,3,10,18,25,30] if duration == 30 else [0,3,10,17,24,31,39,45]
        for shot, start, end in zip(shots, cuts, cuts[1:]):
            shot.update(start=start, end=end)
    reference = plan.get("videoReference")
    if reference and reference["cuts"]:
        # Keep titles readable. Move each inner cut to a nearby measured scene transition.
        scale = duration / reference["duration"]
        candidates = [round(t * scale) for t in reference["cuts"]]
        for index in range(len(shots)-1):
            end = shots[index]["end"]
            lower = max(shots[index]["start"] + 2, end - 2)
            upper = min(shots[index+1]["end"] - 2, end + 2, 3 if index == 0 else duration)
            nearby = [t for t in candidates if lower <= t <= upper]
            if nearby:
                shots[index]["end"] = shots[index+1]["start"] = min(nearby,key=lambda t: abs(t-end))
    return shots
