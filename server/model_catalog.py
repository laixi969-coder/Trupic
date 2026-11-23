"""Release evidence and display prices for selectable model catalogs."""
import datetime as dt
from decimal import Decimal, InvalidOperation

CUTOFF = dt.date(2026, 1, 1)
SEED_BLOG = "https://seed.bytedance.com/en/blog/"
# Exact model IDs only. New versions stay hidden until their release is verified.
RELEASES = {}
for ids, day, source in [
    (["bytedance/seedream-v5.5/" + suffix for suffix in ("text-to-image", "edit", "layer-decomposition")],
     "2026-11-09", SEED_BLOG + "more-realistic-images-more-stable-editing-across-100-rounds-introducing-seedream-5-5"),
    (["bytedance/seedream-v5.0-pro/" + suffix for suffix in ("text-to-image", "edit", "layer-decomposition")],
     "2026-07-08", SEED_BLOG + "beyond-generation-it-understands-design-introducing-seedream-5-0-pro"),
    (["bytedance/seedream-v5.0-lite", "bytedance/seedream-v5.0-lite/edit",
      "bytedance/seedream-v5.0-lite/sequential", "bytedance/seedream-v5.0-lite/edit-sequential"],
     "2026-02-13", SEED_BLOG + "deeper-thinking-more-accurate-generation-introducing-seedream-5-0-lite"),
    (["bytedance/seedance-2.0/" + suffix for suffix in ("text-to-video", "image-to-video")],
     "2026-02-12", SEED_BLOG + "official-launch-of-seedance-2-0"),
    (["bytedance/seedance-2.5/" + suffix for suffix in ("text-to-video", "image-to-video")],
     "2026-07-31", SEED_BLOG + "one-take-creation-flexible-referencing-introducing-seedance-2-5"),
    (["deepseek-ai/deepseek-v4.1-flash", "deepseek-v4.1-flash"],
     "2026-09-10", "https://api-docs.deepseek.com/updates/"),
    (["deepseek-ai/deepseek-v4-pro-0813"],
     "2026-08-13", "https://api-docs.deepseek.com/news/news260813/"),
]:
    for model_id in ids:
        RELEASES[model_id] = (day, source)


def release_date(value):
    try:
        if isinstance(value, str):
            return dt.date.fromisoformat(value[:10])
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return dt.datetime.fromtimestamp(value, dt.UTC).date()
    except (ValueError, OverflowError, OSError):
        pass
    return None


def release_metadata(row, source):
    """Only explicit publication fields qualify; generic created timestamps do not."""
    model_id = row.get("model") or row.get("id")
    if model_id in RELEASES:
        day, evidence = RELEASES[model_id]
        return dict(released=day, releaseSource=evidence)
    for key in ("published_time", "release_date", "released_at"):
        day = release_date(row.get(key))
        if day:
            return dict(released=day.isoformat(), releaseSource=source)
    return {}


def catalog_view(rows):
    visible = []
    unknown = old = future = 0
    today = dt.datetime.now(dt.UTC).date()
    for row in rows:
        row = dict(row)
        if row["id"] in RELEASES:
            row["released"], row["releaseSource"] = RELEASES[row["id"]]
        day = release_date(row.get("released")) if row.get("releaseSource") else None
        if day is None:
            unknown += 1
        elif day < CUTOFF:
            old += 1
        elif day > today:
            future += 1
        else:
            visible.append(row)
    visible.sort(key=lambda row: (row["released"], row["id"]), reverse=True)
    return dict(models=visible, hiddenUnknown=unknown, hiddenOlder=old, hiddenFuture=future,
                releaseCutoff=CUTOFF.isoformat())


def amount(value):
    try:
        number = Decimal(str(value))
        if number.is_finite() and number >= 0:
            return format(number, "f")
    except InvalidOperation:
        pass
    return None


def atlas_price(row):
    price = row.get("price")
    if not isinstance(price, dict):
        return {}
    actual = price.get("actual")
    if not isinstance(actual, dict):
        return {}
    if row.get("type") == "Text":
        parts = []
        for key, label in (("input_price", "输入"), ("output_price", "输出"), ("cache_price", "缓存输入")):
            value = amount(actual.get(key))
            if value is not None:
                parts.append(f"{label} USD {value}/百万 tokens")
        summary = " · ".join(parts)
    else:
        value = amount(actual.get("base_price"))
        if value is None:
            return {}
        units = {"image": "张", "second": "秒", "generation": "次生成",
                 "minute": "分钟", "1k_chars": "千字符"}
        unit = units.get(actual.get("unit"))
        summary = f"USD {value}/{unit}" if unit else f"基础价 USD {value}（单位待核实）"
    if not summary:
        return {}
    note = "平台公开目录价格，实际费用以账号及请求参数为准。"
    if actual.get("prompt_thresholds") or price.get("tiered_price"):
        note = "阶梯基础价，上下文长度可能改变输入及输出单价。" + note
    elif row.get("type") != "Text":
        note = "尺寸、时长、分辨率等参数可能影响费用。" + note
    return dict(priceLabel=summary, priceNote=note,
                priceSource="https://www.atlascloud.ai/pricing/models")
