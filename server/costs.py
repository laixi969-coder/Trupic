"""Operator-supplied spending estimates and separately reconciled provider bills."""

import datetime as dt
import os
import re
from decimal import Decimal, InvalidOperation

from .store import audit, now

KINDS = ("text", "image", "video", "vision")
SCALE = 1_000_000


def units(value):
    try:
        amount = Decimal(str(value))
        if (
            not amount.is_finite()
            or not 0 <= amount <= 1_000_000_000
            or amount != amount.quantize(Decimal(".000001"))
        ):
            raise ValueError
        return int(amount * SCALE)
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError("金额须为非负数，最多六位小数。")


def budget():
    limit = os.getenv("TRUPIC_DAILY_BUDGET_CNY", "").strip()
    return units(limit) if limit else None


def reserve(c, day, kind):
    limit = budget()
    if limit is None:
        return
    price = os.getenv(f"TRUPIC_{kind.upper()}_RESERVE_CNY")
    if price is None:
        raise ValueError("已启用金额预算，请先配置此能力的单次预留金额。")
    amount = units(price)
    row = c.execute(
        "SELECT amount FROM provider_reserve WHERE day=?", (day,)
    ).fetchone()
    if (row[0] if row else 0) + amount > limit:
        raise ValueError("已达当日模型金额预算。")
    c.execute(
        """INSERT INTO provider_reserve VALUES(?,?)
                 ON CONFLICT(day) DO UPDATE SET amount=amount+excluded.amount""",
        (day, amount),
    )


def reconcile(c, actor, data):
    def field(key, size):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > size:
            raise ValueError("请填写完整的模型账单信息。")
        return value.strip()

    day = dt.date.fromisoformat(field("day", 10)).isoformat()
    if day > now()[:10]:
        raise ValueError("账单日期不能晚于今天。")
    platform, model = field("platform", 80), field("model", 180)
    kind, currency = field("kind", 12), field("currency", 3).upper()
    if kind not in KINDS or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("请核对能力与账单币种代码。")
    amount, source = units(data.get("amount")), field("source", 220)
    c.execute(
        """INSERT INTO provider_bill VALUES(?,?,?,?,?,?,?,?)
                 ON CONFLICT(day,platform,model,kind,currency) DO UPDATE SET
                 amount=excluded.amount,source=excluded.source,updated=excluded.updated""",
        (day, platform, model, kind, currency, amount, source, now()),
    )
    audit(
        c,
        actor,
        "核对模型账单",
        f"{day} {platform} {model} {kind} {Decimal(amount) / SCALE} {currency}",
    )


def overview(c):
    limit = budget()
    row = c.execute(
        "SELECT amount FROM provider_reserve WHERE day=?", (now()[:10],)
    ).fetchone()
    return {
        "limit": limit / SCALE if limit is not None else None,
        "reserved": (row[0] if row else 0) / SCALE,
        "bills": [
            dict(r, amount=str(Decimal(r["amount"]) / SCALE))
            for r in c.execute(
                "SELECT * FROM provider_bill ORDER BY day DESC,updated DESC LIMIT 100"
            )
        ],
    }
