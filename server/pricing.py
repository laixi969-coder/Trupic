"""Versioned internal-test tariffs. A signed quote keeps its own tariff until it expires."""

import json

from .store import audit, dump, now

DEFAULT = dict(
    copy=0,
    poster=4,
    video=12,
    video30=24,
    video45=36,
    revision=1,
    trial=120,
    trialDays=30,
)
KINDS = ("copy", "poster", "video")


def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS tariff(
        version INTEGER PRIMARY KEY, rates TEXT NOT NULL, actor TEXT NOT NULL, created TEXT NOT NULL)""")
    c.execute(
        "INSERT OR IGNORE INTO tariff VALUES(1,?,?,?)", (dump(DEFAULT), "system", now())
    )


def current(c):
    row = c.execute(
        "SELECT version,rates FROM tariff ORDER BY version DESC LIMIT 1"
    ).fetchone()
    return {**DEFAULT, **json.loads(row["rates"]), "version": row["version"]}


def update(c, actor, values):
    before = current(c)
    if values.get("version") != before["version"]:
        raise ValueError("计价已更新，请重新加载后保存。")
    rates = {key: values.get(key) for key in DEFAULT}
    if (
        any(type(v) is not int or not 0 <= v <= 1_000_000 for v in rates.values())
        or rates["revision"] < 1
        or not 1 <= rates["trialDays"] <= 3650
    ):
        raise ValueError("请填写有效的整数积分，修改费用至少为 1 积分。")
    c.execute(
        "INSERT INTO tariff(rates,actor,created) VALUES(?,?,?)",
        (dump(rates), actor, now()),
    )
    audit(c, actor, "更新积分定价", dump({"before": before, "after": current(c)}))


def snapshot(spec, rates, item=None):
    item = item or spec["kind"]
    spec["pricingSnapshot"] = dict(
        version=rates["version"], item=item, cost=rates[item]
    )
    return rates[item]


def quoted_cost(spec):
    # Signed quotes from before tariff versioning used exactly this price list.
    return spec.get("pricingSnapshot", {}).get("cost", DEFAULT[spec["kind"]])


def available(c, tenant):
    return c.execute(
        """SELECT credits - COALESCE((SELECT SUM(cost) FROM job
        WHERE tenant=merchant.id AND state IN ('queued','running')),0)
        FROM merchant WHERE id=?""",
        (tenant,),
    ).fetchone()[0]
