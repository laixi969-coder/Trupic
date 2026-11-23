"""Merchant orders, calendar-month entitlement and signed settlement from a payment bridge."""

import calendar
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import urlsplit

from flask import abort, jsonify, request

from . import wallet, growth, coupons
from .store import audit, db, dump, ident, now


def month_after(value, n):
    stamp = dt.datetime.fromisoformat(value)
    year, month = divmod(stamp.year * 12 + stamp.month - 1 + n, 12)
    return stamp.replace(
        year=year,
        month=month + 1,
        day=min(stamp.day, calendar.monthrange(year, month + 1)[1]),
    ).isoformat(timespec="seconds")


def initialize(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS plan_offer(id TEXT PRIMARY KEY,name TEXT NOT NULL,cycle TEXT NOT NULL,
        cents INTEGER NOT NULL,credits INTEGER NOT NULL,bonus INTEGER NOT NULL,enabled INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS purchase(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,request_key TEXT NOT NULL,
        offer TEXT NOT NULL,snapshot TEXT NOT NULL,cents INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
        created TEXT NOT NULL,paid TEXT,receipt TEXT UNIQUE,UNIQUE(tenant,request_key));
    CREATE TABLE IF NOT EXISTS subscription_cursor(order_id TEXT PRIMARY KEY,months_issued INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS subscription(order_id TEXT PRIMARY KEY,tenant TEXT NOT NULL,starts TEXT NOT NULL,
        ends TEXT NOT NULL,months INTEGER NOT NULL,credits INTEGER NOT NULL);
    """)


def subscription(c, t):
    return c.execute(
        "SELECT * FROM subscription WHERE tenant=? AND starts<=? AND ends>? ORDER BY ends DESC LIMIT 1",
        (t, now(), now()),
    ).fetchone()


def issue_due(c, t):
    at = now()
    rows = c.execute(
        """SELECT s.*,COALESCE(p.months_issued,0) issued FROM subscription s
        LEFT JOIN subscription_cursor p ON p.order_id=s.order_id
        WHERE s.tenant=? AND s.starts<=? AND COALESCE(p.months_issued,0)<s.months""",
        (t, at),
    ).fetchall()
    for s in rows:
        issued = s["issued"]
        for i in range(issued, s["months"]):
            starts, ends = month_after(s["starts"], i), month_after(s["starts"], i + 1)
            if starts > at:
                break
            wallet.grant(
                c, t, "套餐月度积分", s["order_id"] + f":month:{i}", s["credits"], ends
            )
            issued = i + 1
        if issued != s["issued"]:
            c.execute(
                "INSERT INTO subscription_cursor VALUES(?,?) ON CONFLICT(order_id) DO UPDATE SET months_issued=excluded.months_issued",
                (s["order_id"], issued),
            )
    wallet.expire(c, t)


def checkout_url(order):
    base = os.environ.get("TRUPIC_CHECKOUT_URL", "").rstrip("/")
    return (
        base + "/" + order
        if urlsplit(base).scheme == "https"
        and urlsplit(base).netloc
        and os.getenv("TRUPIC_PAYMENT_SECRET")
        else None
    )


def verify_bridge(message):
    secret = os.getenv("TRUPIC_PAYMENT_SECRET")
    stamp = request.headers.get("X-Payment-Timestamp", "")
    signature = request.headers.get("X-Payment-Signature", "")
    if (
        not secret
        or not re.fullmatch(r"[0-9]{10}", stamp)
        or abs(time.time() - int(stamp)) > 300
    ):
        abort(403)
    digest = hmac.new(
        secret.encode(), stamp.encode() + b"." + message, hashlib.sha256
    ).hexdigest()
    if not re.fullmatch("[a-f0-9]{64}", signature) or not hmac.compare_digest(
        digest, signature
    ):
        abort(403)


def fulfill(c, row, receipt):
    t, oid = row["tenant"], row["id"]
    offer = json.loads(row["snapshot"])
    previous = c.execute(
        "SELECT id FROM purchase WHERE receipt=?", (receipt,)
    ).fetchone()
    if previous and previous["id"] != oid:
        raise ValueError("支付凭证已关联其他订单。")
    if row["state"] == "paid":
        if row["receipt"] != receipt:
            raise ValueError("支付凭证与已结算订单不同。")
        return
    if row["state"] != "pending":
        raise ValueError("订单状态不支持结算。")
    if offer["cycle"] == "pack":
        wallet.grant(c, t, "购买积分包", oid + ":pack", offer["credits"])
        expiry = None
    else:
        last = c.execute(
            "SELECT MAX(ends) FROM subscription WHERE tenant=?", (t,)
        ).fetchone()[0]
        start = max(last or "", now())
        months = {"month": 1, "year": 12}[offer["cycle"]]
        expiry = month_after(start, months)
        c.execute(
            "INSERT INTO subscription VALUES(?,?,?,?,?,?)",
            (oid, t, start, expiry, months, offer["credits"]),
        )
        issue_due(c, t)
    if offer["bonus"]:
        wallet.grant(c, t, "订单赠送积分", oid + ":bonus", offer["bonus"], expiry)
    c.execute(
        "UPDATE purchase SET state='paid',paid=?,receipt=? WHERE id=?",
        (now(), receipt, oid),
    )
    c.execute("UPDATE redemption SET status='paid' WHERE order_id=?", (oid,))
    growth.milestone(
        c,
        t,
        "paid",
        oid,
        row["cents"],
        offer.get("attribution"),
        offer.get("growthRules"),
    )
    audit(c, "payment-bridge", "收款核对并发放权益", oid)


def refund(c, row, receipt):
    oid, t = row["id"], row["tenant"]
    if row["state"] not in ("paid", "refunded") or row["receipt"] != receipt:
        raise ValueError("退款须关联已支付的原凭证。")
    if row["state"] == "refunded":
        return
    c.execute("UPDATE purchase SET state='refunded' WHERE id=?", (oid,))
    c.execute("DELETE FROM subscription WHERE order_id=?", (oid,))
    # Revoke only this order's remaining lots. Held credits expire if their job releases them.
    c.execute(
        "UPDATE credit_lot SET expires=? WHERE tenant=? AND substr(ref,1,?)=?",
        (now(), t, len(oid) + 1, oid + ":"),
    )
    wallet.expire(c, t)
    reward = c.execute(
        "SELECT snapshot FROM reward_stage WHERE guest=? AND stage='paid' AND reference=?",
        (t, oid),
    ).fetchone()
    if reward:
        rule = json.loads(reward["snapshot"])
        for recipient, key in ((t, "Guest"), (rule.get("owner"), "Owner")):
            if recipient:
                c.execute(
                    "UPDATE credit_lot SET expires=? WHERE tenant=? AND ref=?",
                    (now(), recipient, "invite:" + t + ":paid:" + key),
                )
                wallet.expire(c, recipient)
    c.execute("UPDATE redemption SET status='refunded' WHERE order_id=?", (oid,))
    c.execute(
        """UPDATE commission SET status=CASE status WHEN 'settled' THEN 'recovery_due' ELSE 'reversed' END
        WHERE order_id=?""",
        (oid,),
    )
    audit(c, "payment-bridge", "原单全额退款并冲回权益", oid)


def register(app, services):
    with db() as c:
        initialize(c)

    def beneficiary(c, actor, login):
        if not login:
            return actor
        m = c.execute("SELECT id FROM merchant WHERE login=?", (login,)).fetchone()
        if not m or not growth.can_assist(c, actor, m[0]):
            abort(403)
        return m[0]

    @app.get("/api/shop")
    def shop():
        t = services["reqtenant"]()
        with db() as c:
            actor = t
            t = beneficiary(c, actor, request.args.get("merchant"))
            active = subscription(c, t)
            offers = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM plan_offer WHERE enabled=1 ORDER BY cents"
                )
                if active or r["cycle"] != "pack"
            ]
            orders = [
                dict(r)
                for r in c.execute(
                    "SELECT id,snapshot,cents,state,created,paid FROM purchase WHERE tenant=? AND (?=tenant OR json_extract(snapshot,'$.initiator')=?) ORDER BY created DESC,rowid DESC",
                    (t, actor, actor),
                )
            ]
            for order in orders:
                order["name"] = json.loads(order.pop("snapshot"))["name"]
                order["checkout"] = (
                    checkout_url(order["id"]) if order["state"] == "pending" else None
                )
            return jsonify(
                offers=offers,
                orders=orders,
                subscription=dict(active) if active else None,
                canPay=bool(checkout_url("order")),
            )

    @app.post("/api/orders")
    def order():
        t, v = services["reqtenant"](), services["body"]()
        key = services["string"](v.get("requestKey"), 90)
        if not key:
            raise ValueError("请重新打开订单。")
        with db(True) as c:
            actor = t
            t = beneficiary(c, actor, v.get("merchant"))
            old = c.execute(
                "SELECT * FROM purchase WHERE tenant=? AND request_key=?", (t, key)
            ).fetchone()
            if old:
                snapshot = json.loads(old["snapshot"])
                if (
                    snapshot.get("initiator", t) != actor
                    or old["offer"] != v.get("offer")
                    or snapshot.get("coupon", "")
                    != services["string"](v.get("coupon"), 64)
                    or old["cents"] != v.get("cents")
                ):
                    raise ValueError("请求编号已用于另一笔订单。")
                return jsonify(
                    id=old["id"],
                    checkout=checkout_url(old["id"])
                    if old["state"] == "pending"
                    else None,
                )
            if not checkout_url("order"):
                raise ValueError("支付通道尚未开通。")
            if not c.execute("SELECT login FROM merchant WHERE id=?", (t,)).fetchone()[
                0
            ]:
                raise ValueError("购买前请先绑定商家账号。")
            offer = c.execute(
                "SELECT * FROM plan_offer WHERE id=? AND enabled=1", (v.get("offer"),)
            ).fetchone()
            if not offer or offer["cycle"] == "pack" and not subscription(c, t):
                raise ValueError("此商品当前不可购买。")
            code = services["string"](v.get("coupon"), 64)
            total = coupons.calculate(c, t, offer, code)
            if (
                type(v.get("cents")) is not int
                or total != v["cents"]
                or v.get("credits") != offer["credits"]
                or v.get("bonus") != offer["bonus"]
            ):
                raise ValueError("套餐权益已更新，请刷新后确认。")
            oid = ident()
            c.execute(
                "INSERT INTO purchase(id,tenant,request_key,offer,snapshot,cents,created) VALUES(?,?,?,?,?,?,?)",
                (
                    oid,
                    t,
                    key,
                    offer["id"],
                    dump(
                        {
                            **dict(offer),
                            "coupon": code,
                            "initiator": actor,
                            "attribution": growth.attribution(c, t),
                            "growthRules": growth.rules(c),
                        }
                    ),
                    total,
                    now(),
                ),
            )
            if code:
                c.execute(
                    "INSERT INTO redemption VALUES(?,?,?,'reserved')", (oid, code, t)
                )
            return jsonify(id=oid, checkout=checkout_url(oid))

    @app.get("/api/payments/orders/<oid>")
    def invoice(oid):
        verify_bridge(("GET " + request.path).encode())
        with db() as c:
            row = c.execute(
                "SELECT id,cents,snapshot,state FROM purchase WHERE id=?", (oid,)
            ).fetchone()
            if not row:
                abort(404)
            return jsonify(
                order=row["id"],
                cents=row["cents"],
                currency="CNY",
                name=json.loads(row["snapshot"])["name"],
                status=row["state"],
            )

    @app.post("/api/payments/webhook")
    def paid():
        verify_bridge(request.get_data())
        v = services["body"]()
        with db(True) as c:
            row = c.execute(
                "SELECT * FROM purchase WHERE id=?", (v.get("order"),)
            ).fetchone()
            if not row:
                abort(404)
            if (
                v.get("status") not in ("paid", "refunded", "cancelled")
                or v.get("currency") != "CNY"
                or type(v.get("cents")) is not int
                or v["cents"] != row["cents"]
                or not isinstance(v.get("receipt"), str)
                or not re.fullmatch(r"[\w.-]{1,100}", v["receipt"])
            ):
                raise ValueError("支付状态、金额或凭证不符。")
            if v["status"] == "cancelled":
                if row["state"] not in ("cancelled", "pending"):
                    raise ValueError("只能关闭未支付订单。")
                c.execute(
                    "UPDATE purchase SET state='cancelled' WHERE id=?", (row["id"],)
                )
                c.execute(
                    "UPDATE redemption SET status='cancelled' WHERE order_id=?",
                    (row["id"],),
                )
            elif v["status"] == "refunded":
                refund(c, row, v["receipt"])
            else:
                fulfill(c, row, v["receipt"])
        return jsonify(ok=True)

    @app.route("/api/admin/offers", methods=["POST", "GET"])
    def offers():
        services["require_admin"]()
        t = services["reqtenant"]()
        with db(request.method == "POST") as c:
            if request.method == "POST":
                v = services["body"]()
                if (
                    not isinstance(v.get("name"), str)
                    or not v["name"].strip()
                    or v.get("cycle") not in ("month", "year", "pack")
                    or any(
                        type(v.get(k)) is not int or not 0 <= v[k] <= 10_000_000
                        for k in ("cents", "credits", "bonus")
                    )
                    or min(v["cents"], v["credits"]) < 1
                ):
                    raise ValueError("请填写套餐名称、周期、正整数价格（分）和积分。")
                oid = ident()
                c.execute(
                    "INSERT INTO plan_offer VALUES(?,?,?,?,?,?,1)",
                    (
                        oid,
                        v["name"].strip()[:60],
                        v["cycle"],
                        v["cents"],
                        v["credits"],
                        v["bonus"],
                    ),
                )
                audit(c, t, "上架套餐或积分包", oid)
            return jsonify(
                [
                    dict(r)
                    for r in c.execute("SELECT * FROM plan_offer ORDER BY rowid DESC")
                ]
            )

    @app.post("/api/admin/offers/<oid>/disable")
    def disable(oid):
        services["require_admin"]()
        t = services["reqtenant"]()
        with db(True) as c:
            if not c.execute(
                "UPDATE plan_offer SET enabled=0 WHERE id=?", (oid,)
            ).rowcount:
                abort(404)
            audit(c, t, "下架套餐或积分包", oid)
        return jsonify(ok=True)
