"""Platform-issued fixed discounts. Pending orders reserve a redemption atomically."""

import datetime as dt
from flask import abort, jsonify, request
from .store import audit, db, ident, now


def calculate(c, t, offer, code):
    if not code:
        return offer["cents"]
    row = c.execute("SELECT * FROM coupon WHERE code=?", (code,)).fetchone()
    if (
        not row
        or not row["starts"] <= now()[:10] <= row["ends"]
        or row["offer"] != offer["id"]
        or offer["cents"] < row["threshold"]
    ):
        raise ValueError("优惠券不适用于当前订单。")
    if (
        row["agent"]
        and not c.execute(
            "SELECT 1 FROM attribution a JOIN channel_agent rep ON rep.tenant=a.owner WHERE a.guest=? AND a.owner=? AND a.kind='agent' AND rep.enabled=1",
            (t, row["agent"]),
        ).fetchone()
    ):
        raise ValueError("优惠券仅限所属渠道商家。")
    used, personal = c.execute(
        "SELECT COUNT(*),COALESCE(SUM(tenant=?),0) FROM redemption WHERE code=? AND status!='cancelled'",
        (t, code),
    ).fetchone()
    if used >= row["quantity"] or personal >= row["per_user"]:
        raise ValueError("优惠券已用完或已达到个人使用次数。")
    return offer["cents"] - row["discount"]


def register(app, services):
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS coupon(code TEXT PRIMARY KEY,offer TEXT NOT NULL,discount INTEGER NOT NULL,
            threshold INTEGER NOT NULL,starts TEXT NOT NULL,ends TEXT NOT NULL,quantity INTEGER NOT NULL,per_user INTEGER NOT NULL,agent TEXT);
        CREATE TABLE IF NOT EXISTS redemption(order_id TEXT PRIMARY KEY,code TEXT NOT NULL,tenant TEXT NOT NULL,status TEXT NOT NULL);
        """)

    @app.post("/api/orders/price")
    def price():
        t, v = services["reqtenant"](), services["body"]()
        with db() as c:
            if v.get("merchant"):
                from .growth import can_assist

                m = c.execute(
                    "SELECT id FROM merchant WHERE login=?", (v["merchant"],)
                ).fetchone()
                if not m or not can_assist(c, t, m[0]):
                    abort(403)
                t = m[0]
            offer = c.execute(
                "SELECT * FROM plan_offer WHERE id=? AND enabled=1", (v.get("offer"),)
            ).fetchone()
            if not offer:
                abort(404)
            return jsonify(
                cents=calculate(c, t, offer, services["string"](v.get("coupon"), 64))
            )

    @app.get("/api/admin/coupons/<code>/redemptions")
    def redemptions(code):
        services["require_admin"]()
        with db() as c:
            return jsonify([dict(r) for r in c.execute("""SELECT r.order_id,r.status,m.login,p.created,p.cents
                FROM redemption r JOIN purchase p ON p.id=r.order_id JOIN merchant m ON m.id=r.tenant
                WHERE r.code=? ORDER BY p.created DESC,p.rowid DESC""",(code,))])

    @app.route("/api/admin/coupons", methods=["GET", "POST"])
    def coupons():
        services["require_admin"]()
        actor = services["reqtenant"]()
        with db(request.method == "POST") as c:
            if request.method == "POST":
                v = services["body"]()
                offer = c.execute(
                    "SELECT * FROM plan_offer WHERE id=? AND enabled=1",
                    (v.get("offer"),),
                ).fetchone()
                if not offer:
                    raise ValueError("请选择已上架的套餐。")
                for k in ("starts", "ends"):
                    try:
                        v[k] = dt.date.fromisoformat(v[k]).isoformat()
                    except (TypeError, ValueError, KeyError):
                        raise ValueError("请填写有效期。")
                if (
                    any(
                        type(v.get(k)) is not int or not 0 <= v[k] <= 10_000_000
                        for k in ("discount", "threshold", "quantity", "per_user")
                    )
                    or not 0 < v["discount"] < offer["cents"]
                    or v["threshold"] > offer["cents"]
                    or not 0 < v["per_user"] <= v["quantity"]
                    or v["ends"] < v["starts"]
                ):
                    raise ValueError("请核对折扣、门槛、期限及使用次数，实付须大于零。")
                agent = None
                if v.get("agent"):
                    a = c.execute(
                        "SELECT a.tenant FROM channel_agent a JOIN merchant m ON a.tenant=m.id WHERE m.login=? AND a.enabled=1",
                        (v["agent"],),
                    ).fetchone()
                    if not a:
                        raise ValueError("渠道账号不存在。")
                    agent = a[0]
                code = ident()[:16]
                c.execute(
                    "INSERT INTO coupon VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        code,
                        offer["id"],
                        v["discount"],
                        v["threshold"],
                        v["starts"],
                        v["ends"],
                        v["quantity"],
                        v["per_user"],
                        agent,
                    ),
                )
                audit(c, actor, "创建优惠券", code)
            return jsonify(
                [
                    dict(r)
                    for r in c.execute("""SELECT c.*,o.name,
                (SELECT COUNT(*) FROM redemption r WHERE r.code=c.code AND r.status='paid') AS redeemed
                FROM coupon c JOIN plan_offer o ON o.id=c.offer ORDER BY c.rowid DESC""")
                ]
            )
