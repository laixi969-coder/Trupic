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
EXPLICIT = [
    ("杂志|编辑风|报纸|宋体|文艺", "editorial"),
    ("丝印|电影海报|mondo|演出|音乐节", "screenprint"),
    ("瑞士|促销网格|价格主视觉|放大价格|突出价格|网格排版", "swiss"),
    ("商品主视觉|品牌\\s*KV|产品特写", "product"),
]


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
        brief = plan["original"]
        key = next(
            (style for words, style in EXPLICIT if re.search(words, brief, re.I)), None
        )
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
    keys = list(STYLES)
    key = keys[(keys.index(current["id"]) + 1) % len(keys)]
    return {"id": key, "selection": "auto", **STYLES[key]}
