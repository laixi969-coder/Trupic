"""Trupic's original compositions and their commercial routing criteria."""

import re
import json
from pathlib import Path

RULES = (
    Path(__file__).resolve().parents[1]
    / ".agents/skills/trupic-commercial-poster/references/directions.json"
)
DIRECTIONS = json.loads(RULES.read_text())


def direction(brief, profile):
    for text in (brief, profile.get("product", ""), profile.get("industry", "")):
        for key, rule in DIRECTIONS.items():
            if rule.get("match") and re.search(rule["match"], text, re.I):
                return key, rule
    return "general", DIRECTIONS["general"]


def industry_examples():
    return [
        {
            "id": key,
            "name": art["name"],
            "shot": art["shot"],
            "focus": art["focus"],
            "colors": [art["ink"], art["paper"], art["accent"]],
            "type": style_type(art["example"]["style"], art),
            **{field: art["example"][field] for field in ("title", "brief", "style")},
        }
        for key, art in DIRECTIONS.items()
        if "example" in art
    ]


STYLES = {
    "product": {
        "name": "全幅商品主视觉",
        "intent": "让商品、光线和标题共用一张满版画面。",
        "scene": "近景单主体，横向画面重心居中，保留商品轮廓与周围呼吸空间。",
        "type": "思源黑体 / Barlow Condensed",
    },
    "editorial": {
        "name": "杂志编辑",
        "intent": "大宋体沿主图留白排放，小字做边注。",
        "scene": "自然侧光与安静的材质细节，以横向取景留出干净边缘。",
        "type": "思源宋体 / 思源黑体 / Barlow Condensed",
    },
    "swiss": {
        "name": "价格主视觉",
        "intent": "让价格直接进入摄影场景，单位和适用条件跟随价格。",
        "scene": "给数字预留连续、安静的色面，商品或活动道具与价格共享光线和底色。",
        "type": "Barlow Condensed / 思源黑体",
    },
    "screenprint": {
        "name": "活动丝印",
        "intent": "用有限色网点、叠印大字与物件轮廓表现活动。",
        "scene": "强轮廓与侧向光，主体集中，适合双色丝印画面。",
        "type": "Barlow Condensed / 思源黑体",
    },
}
STYLES.update(
    {
        "riso": {
            "name": "单双色孔版",
            "intent": "以原图中的局部形状和纸色组织印刷画面，商家的商品主体保留原色。",
            "scene": "纸张底色、局部网点和一至两种印色。",
            "type": "思源宋体 / Barlow Condensed",
        },
        "ipscene": {
            "name": "品牌 IP 场景",
            "intent": "把角色原稿置于与活动有关的场景，保留角色轮廓、品牌色和配件。",
            "scene": "用角色视线与前景道具形成对角关系，预留标题区。",
            "type": "思源黑体 / Barlow Condensed",
        },
        "food-motion": {
            "name": "食欲定格",
            "intent": "让菜品或食材成为第一眼，保留照片中真实的动作与细节。",
            "scene": "以餐具、食材或光束建立方向，使用明快色面或暗调聚光。",
            "type": "思源黑体 / Barlow Condensed",
        },
        "quiet-light": {
            "name": "留白光影",
            "intent": "用集中的侧光和小面积实物建立尺度，给标题留连续空间。",
            "scene": "单一主体、清楚的受光面与较安静的背景，避免杂物打断留白。",
            "type": "思源宋体 / 思源黑体",
        },
        "photo-grid": {
            "name": "照片编排",
            "intent": "保留整张照片，用取景边、文字基线和留白组织叙事。",
            "scene": "以一张完整照片为视觉锚点，用原片明暗和方向决定版面。",
            "type": "思源黑体 / Barlow Condensed",
        },
    }
)
EXPLICIT = [
    (
        "孔版|单色印刷|双色印刷|单色海报|双色海报|蓝晒|risograph|photo.riso|mono.color",
        "riso",
    ),
    (r"品牌\s*IP|IP\s*场景|吉祥物|角色场景", "ipscene"),
    (r"食欲定格|日式美食|日式餐饮|美食动势|食材悬停|筷子.{0,6}(夹起|挑起)|面条.{0,6}(拉起|挑起)", "food-motion"),
    (r"留白光影|静物留白|低调侧光|留白.{0,4}侧光|光影.{0,4}留白", "quiet-light"),
    (r"照片编排|相册海报|照片叙事|摄影排版|旅行海报|照片.{0,5}(对齐线|透视线)", "photo-grid"),
    ("杂志|编辑风|报纸|宋体|文艺", "editorial"),
    ("丝印|电影海报|mondo|演出|音乐节", "screenprint"),
    ("瑞士|促销网格|价格主视觉|放大价格|突出价格|网格排版", "swiss"),
    ("商品主视觉|品牌\\s*KV|产品特写", "product"),
]


def visual_requests(brief):
    """Return affirmative directions, so e.g. 不要孔版 cannot select the print route."""
    clauses = re.split(r"[，,。；;！？\n]", brief)
    return "。".join(
        re.split(r"不要|避免|禁止|不用|别用|不想|不需要|不使用|不采用", clause, maxsplit=1)[0]
        for clause in clauses
    )


def requested_style(brief):
    affirmative = visual_requests(brief)
    return next((style for words, style in EXPLICIT if re.search(words, affirmative, re.I)), None)


def style_type(style, art):
    if style == "editorial" or (style == "product" and art["type"] == "serif"):
        return "思源宋体 / 思源黑体 / Barlow Condensed"
    return STYLES[style]["type"]


def choose_style(plan, selection="auto"):
    if selection != "auto" and selection not in STYLES:
        raise ValueError("请选择有效的海报风格。")
    if selection != "auto":
        key = selection
    else:
        brief = visual_requests(plan["original"])
        key = requested_style(plan["original"])
        if not key:
            if re.search(r"满\s*\d+|\d+\s*折|优惠|促销|折扣|价目|第二杯|买一", brief):
                key = "swiss"
            elif re.search("赛事|比赛|派对|组局|活动|开幕|球赛|放映", brief):
                key = "screenprint"
            elif re.search("品牌故事|知识|生活方式|香氛|书店|花艺|文化|展览", brief):
                key = "editorial"
            else:
                key = direction(brief, plan.get("profile", {}))[1]["style"]
    art = (
        DIRECTIONS.get(plan.get("sector"))
        or direction(plan["original"], plan.get("profile", {}))[1]
    )
    return {
        "id": key,
        "selection": selection,
        **STYLES[key],
        "type": style_type(key, art),
    }


def next_style(current):
    # Existing brand characters require an explicit character brief and reference.
    keys = [k for k in STYLES if k != "ipscene"]
    if current["id"] not in keys:
        return {"id": keys[0], "selection": "auto", **STYLES[keys[0]]}
    key = keys[(keys.index(current["id"]) + 1) % len(keys)]
    return {"id": key, "selection": "auto", **STYLES[key]}


def layout_alternative(plan, copy, kind):
    design = plan.get("design") or choose_style(plan)
    current = design["id"]
    if kind == "poster" and current == "photo-grid":
        mode = "framed" if design.get("photoLayout") == "bleed" else "bleed"
        reading = design.get("readingOrder", {})
        if mode == "framed":
            label, intent = "切回取景框", "沿原片外缘留纸边，标题与照片分区。"
        elif copy.get("offer") and reading.get("first", "offer") == "offer":
            label = "突出优惠与有效期" if re.search(r"有效期|截至|活动时间|活动日期", copy.get("terms") or "") else "突出优惠"
            intent = "放大已确认的优惠，有适用条件时紧跟优惠排字。"
        else:
            label, intent = "换成满版摄影", "让照片的边缘光色铺满画幅，按标题实际行数留出连续字区。"
        return {**design, "photoLayout": mode, "buttonLabel": label, "layoutIntent": intent}
    preferred = "swiss" if copy.get("offer") else "editorial"
    return choose_style(plan, "product" if preferred == current else preferred)
