"""Release evidence and display prices for selectable model catalogs."""
import datetime as dt
from decimal import Decimal, InvalidOperation


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
    for key in ("published_time", "release_date", "released_at"):
        day = release_date(row.get(key))
        if day:
            return dict(released=day.isoformat(), releaseSource=source)
    return {}


def catalog_view(rows):
    # The provider catalog defines availability. Dates are optional display metadata.
    # Keep this shared view for both freshly synced and previously cached catalogs.
    return dict(models=sorted((dict(row) for row in rows), key=lambda row: row["id"].casefold()))


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
