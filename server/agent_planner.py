"""Translate a merchant's brief to the existing, allowlisted creative pipeline."""

import json
import re

from . import auto_creation, context_memory, providers
from .formats import RATIOS

KINDS = {"poster": "营销海报", "copy": "推广文案", "video": "宣传短片"}
ORDINAL = re.compile(
    r"^(?:就|请)?(?:选|选用|选择|用|做|要)?第?([一二三123])(?:个|项|条|组|版|张|种|款)(?:吧|方案|文案|主题)?[。！! ]*$"
)
OWN_COPY = re.compile(
    r'(?:已有文案|我的文案|文案(?:用|是|写成)|直接用这句|原文案)[：:\s]*[「“"]([^」”"]+)[」”"]|(?:已有文案|我的文案|直接用这句|文案用|文案)[:：]\s*(.+)$',
    re.S,
)
DELEGATE = re.compile(r"都由你决定|你来定|你来选|你决定|全权交给你")
OPTIONS = {
    "asset",
    "assetMode",
    "identityRegion",
    "assetConfirmed",
    "references",
    "videoReference",
    "visualDetail",
    "ratio",
    "duration",
    "imageCount",
    "promotedItem",
    "businessGoal",
    "posterStyle",
    "fontId",
    "lettering",
    "source",
    "reference",
    "topicId",
    "kind",
    "ownCopy",
}
ANGLES = {"招聘", "促销", "开业", "上新", "招募", "团购"}


def ordinal(text):
    m = ORDINAL.fullmatch(text.strip())
    return ("一二三".index(m[1]) if m[1] in "一二三" else int(m[1]) - 1) if m else None


def explicit_kind(text):
    if re.search(r"(只|仅)(做|写|要)?(一[份条段])?(文案|文字)|纯文案", text):
        return "copy"
    if re.search(r"视频|短片|短视频|动态海报", text):
        return "video"
    if re.search(r"海报|主图|封面|组图|图片", text):
        return "poster"
    if re.search(r"写.{0,12}(?:文案|朋友圈)|朋友圈配文|推广语", text):
        return "copy"


PRICE_EDIT = re.compile(
    r"(?:把|将)?(?:价格|售价)?(?:从)?\s*(\d+(?:\.\d+)?)\s*元?\s*(?:改为|改成|调为|换成)\s*(\d+(?:\.\d+)?)\s*元[。！]?"
)


def correct_price(values, locked, text):
    correction = PRICE_EDIT.fullmatch(text.strip())
    if not correction:
        return False
    old, new = correction.groups()
    pattern = re.compile(r"(?<![\d.])" + re.escape(old) + r"(?=\s*元)")
    found = False
    for obj, fields in (
        (values, ("brief", "facts", "ownCopy")),
        (locked, ("title", "body", "detailLine", "cta", "terms", "offer")),
    ):
        for key in fields:
            if obj and obj.get(key):
                updated, count = pattern.subn(new, obj[key])
                obj[key] = updated
                found = found or bool(count)
    if not found:
        raise ValueError("当前任务中找不到这个原价，请核对要修改的金额。")
    return True


def task_input(text, options, previous=None):
    values = dict(previous or {})
    if not isinstance(options, dict) or options.keys() - OPTIONS:
        raise ValueError("创作选项无效，请重新选择。")
    for key, value in options.items():
        if key in ("duration", "imageCount"):
            if type(value) is not int:
                raise ValueError("请使用有效的数量和时长。")
        elif key == "assetConfirmed":
            if type(value) is not bool:
                raise ValueError("请核对素材。")
        elif key not in ("references", "identityRegion", "visualDetail") and (
            not isinstance(value, str) or len(value) > 400
        ):
            raise ValueError("创作选项格式无效。")
    values.update(options)
    kind = options.get("kind") or explicit_kind(text) or values.get("kind") or "poster"
    if kind not in KINDS:
        raise ValueError("请选择文案、海报或视频。")
    if kind != values.get("kind") and "ratio" not in options:
        values.pop("ratio", None)
    values.update(kind=kind, brief=text if not previous else previous["brief"])
    if previous and text:
        values["facts"] = "；".join(filter(None, [values.get("facts"), text]))
        if len(values["facts"]) > 400:
            raise ValueError("补充内容超过 400 字，请精简本次补充。")
    for ratio, number in RATIOS.items():
        if f"{number[0]}:{number[1]}" in text.replace("：", ":"):
            values["ratio"] = ratio
    values.setdefault("ratio", "story" if kind == "video" else "portrait")
    if re.search(r"(?:两|二|2)张", text):
        values["imageCount"] = 2
    elif re.search(r"(?:一|1)张", text):
        values["imageCount"] = 1
    if match := re.search(r"(15|30|45)\s*秒", text):
        values["duration"] = int(match[1])
    if match := OWN_COPY.search(text):
        values["ownCopy"] = next(v.strip() for v in match.groups() if v)
    if DELEGATE.search(text):
        values["delegate"] = True
    return values


def provided_copy(text, plan):
    if not isinstance(text, str) or not text.strip() or len(text) > 360:
        raise ValueError("请填写 1–360 字的成稿。可换行区分标题和正文。")
    first, _, rest = text.strip().partition("\n")
    spec = plan["items"][0]["spec"]
    result = dict(spec["replacement"])
    # A long paragraph is body copy. Do not silently truncate a merchant's supplied text.
    if len(first) > 40:
        first, rest = "", text.strip()
    result.update(
        title=first,
        body=rest.strip(),
        cta="",
        detailLine=rest.strip(),
        engine="商家定稿",
    )
    return result


def assemble(c, tenant, project, values):
    profile = json.loads(
        c.execute("SELECT profile FROM merchant WHERE id=?", (tenant,)).fetchone()[0]
    )
    current_text = "；".join(
        filter(None, [values.get("brief"), values.get("facts"), values.get("ownCopy")])
    )
    selected, recalled = context_memory.select_memories(
        c, tenant, project, current_text
    )
    facts = [profile.get("facts", "")]
    price = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*元")
    confirmed = re.search(
        r"本次(?:按|以|用)\s*(\d+(?:\.\d+)?)\s*元(?:为准)?", current_text
    )
    tones = [profile.get("tone", "")]
    source = values.copy()
    used_recalled = []
    for r, meta in zip(selected, recalled):
        if r["kind"] == "asset":
            source.setdefault("asset", r["value"])
            used_recalled.append(meta)
        else:
            if r["kind"] == "fact" and r["name"] in current_text:
                old_prices = set(price.findall(r["value"]))
                # Only compare a price explicitly associated with the same named fact.
                amounts = set(
                    re.findall(
                        re.escape(r["name"])
                        + r"[：:\s为是售价约]*(\d+(?:\.\d+)?)\s*元",
                        current_text,
                    )
                )
                if old_prices and amounts - old_prices:
                    if confirmed and confirmed[1] in amounts:
                        continue
                    raise ValueError(
                        f"记忆里的{r['name']}为{r['value']}，与本次金额不同。请回复「本次以具体金额元为准」。"
                    )
            target = tones if r["kind"] == "preference" else facts
            target.append(r["name"] + "：" + r["value"])
            used_recalled.append(meta)
    profile.update(
        facts="；".join(filter(None, facts)), tone="；".join(filter(None, tones))
    )
    source["deliveryMode"] = {"poster": "image", "video": "video", "copy": None}.get(
        values.get("kind")
    )
    source.setdefault("assetMode", "original")
    source["_recalled"] = used_recalled
    return source, profile


def plan_task(services, c, tenant, project, values):
    source, profile = assemble(c, tenant, project, values)
    recalled = source.pop("_recalled", [])
    if values.get("facts"):
        combined = source["brief"] + "。" + values["facts"]
        if len(combined) > 1200:
            raise ValueError("完整需求超过 1200 字，请缩短补充内容。")
        source["brief"] = combined
    if (
        not profile.get("product")
        and not source.get("asset")
        and not values.get("ownCopy")
        and re.fullmatch(
            r"(?:请|帮我|我想|想要|给我|来|做|制作|生成|写|个|一|张|条|份|宣传|营销|推广|海报|视频|文案|短片|都由你决定|[，。！\s])+",
            source["brief"],
        )
    ):
        return dict(ready=False, message="这次想推广哪件商品、服务或活动？")
    if own := values.get("ownCopy"):
        # Treat explicit, supplied copy like the merchant's written brief for the factual checks.
        profile["facts"] = "；".join(filter(None, [profile.get("facts"), own]))
    result = auto_creation.coordinate(
        services,
        c,
        tenant,
        source,
        agent_context=dict(kind=values["kind"], profile=profile),
    )
    if result.get("shared") is not None:
        result["shared"]["recalledMemories"] = recalled
    for entry in result.get("items", []):
        spec = entry["spec"]
        spec["plan"]["capability"] = CAPABILITIES[spec["kind"]]
    return result


def revision_request(text, base):
    action = "edit"
    if re.search(r"太长|短一点|精简|缩短", text):
        action = "shorten"
    elif re.search(r"换一张|换张图|换图", text):
        action = "image"
    elif re.search(r"构图|排版|版式", text):
        action = "layout"
    elif re.search(r"换个创意|换个角度", text):
        action = "revision"
    for ratio, (w, h) in RATIOS.items():
        if f"{w}:{h}" in text.replace("：", ":"):
            return dict(action="ratio", base=base, ratio=ratio)
    return dict(
        action=action, base=base, instruction=text, duplicate="照这个再做" in text
    )


def revision_plan(services, c, tenant, values):
    ref = values["workRef"]
    work = services["owner"](c, "work", ref["id"], tenant)
    result = services["make_revision_quote"](tenant, work["id"], values["edit"])
    base = c.execute(
        "SELECT copy FROM version WHERE work=? AND n=?", (work["id"], ref["version"])
    ).fetchone()
    cp = json.loads(base[0])
    if result["changes"]:
        cp.update(result["changes"])
    locked = {k: cp.get(k, "") for k in ("title", "body", "cta")}
    brief = dict(deliveries=["作品修改"], facts=[], shortOptions=result["options"])
    return result, brief, locked


# These adapters route only to the versioned, in-process production engines. An uploaded
# reference can supply creative material but cannot register tools or choose a billing action.
CAPABILITIES = {
    "copy": dict(
        id="merchant.copy",
        version=1,
        fallbackVersion=1,
        supportedTasks=["copy", "poster", "video"],
        dependencies=["hiccai-wenan", "copy_choices"],
        routes=["text"],
        inputs=["brief", "facts"],
        inputSchema={"brief": "string(1..1200)", "facts": "string(0..400)"},
        output="copy.txt",
        outputSchema={"title": "string", "body": "string", "cta": "string"},
        timeoutSeconds=45,
        costCap=10,
        permission="merchant:approved_quote",
    ),
    "poster": dict(
        id="merchant.poster",
        version=1,
        fallbackVersion=1,
        supportedTasks=["poster", "revision"],
        dependencies=["trupic-commercial-poster", "layout-grid", "visual_review"],
        routes=["text", "image", "vision"],
        inputs=["brief", "lockedCopy", "assets"],
        inputSchema={"brief": "string", "ratio": "enum", "imageCount": "int(1..2)", "lockedCopy": "object"},
        output="poster.png",
        outputSchema={"png": "binary/png", "copy": "object", "review": "object"},
        timeoutSeconds=120,
        costCap=40,
        permission="merchant:approved_quote",
    ),
    "video": dict(
        id="merchant.video",
        version=1,
        fallbackVersion=1,
        supportedTasks=["video"],
        dependencies=["video_storyboard@1.1.0", "film_timing", "film_edit", "visual_review"],
        routes=["text", "video", "vision"],
        inputs=["brief", "facts", "duration", "assets"],
        inputSchema={"brief": "string", "ratio": "enum", "duration": "enum(15,30,45)"},
        output="video.mp4",
        outputSchema={"mp4": "binary/mp4", "storyboard": "array", "review": "object"},
        timeoutSeconds=300,
        costCap=120,
        permission="merchant:approved_quote",
    ),
}


def capability_registry(c):
    """Return registered capabilities enriched with live provider health status (PRD §22)."""
    overview = providers.overview(c)
    breakers = set(overview.get("openBreakers") or [])
    items = []
    for cap in CAPABILITIES.values():
        degraded = [r for r in cap["routes"] if any(b.endswith(":" + r) or b == r for b in breakers)]
        items.append({**cap, "health": "degraded" if degraded else "healthy", "degradedRoutes": degraded})
    return items
