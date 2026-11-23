"""Explicit staff permissions on ordinary authenticated accounts. Superuser stays separate."""

from flask import jsonify, session
from . import wallet
from .store import audit, db, dump, now

ROLES = {"operations": "运营", "support": "客服", "finance": "财务"}
TABS = {
    "operations": ["works", "visual", "cases", "events"],
    "support": ["merchants"],
    "finance": ["finance", "merchants"],
}


def role(c):
    if not session.get("tenant"):
        return None
    r = c.execute(
        "SELECT role FROM staff_role WHERE tenant=?", (session["tenant"],)
    ).fetchone()
    return r[0] if r else None


def permitted(group, path, method):
    if group not in ROLES:
        return False
    if path == "/api/admin":
        return True
    if group == "finance":
        return (
            path
            in (
                "/api/admin/pricing",
                "/api/admin/offers",
                "/api/admin/coupons",
                "/api/admin/merchants",
                "/api/admin/credits",
            )
            or path.startswith("/api/admin/offers/")
            and path.endswith("/disable")
        )
    if group == "support":
        return path == "/api/admin/merchants" and method == "GET"
    if group == "operations":
        return (
            path.startswith("/api/admin/preview/")
            and method == "GET"
            or path
            in {
                "/api/admin/" + v
                for v in ("review", "case", "approve", "event", "event-sync")
            }
        )
    return False


def register(app, services):
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS staff_role(tenant TEXT PRIMARY KEY,role TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS credit_adjustment(tenant TEXT,ref TEXT,actor TEXT NOT NULL,amount INTEGER NOT NULL,
            reason TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(tenant,ref));
        """)

    @app.get("/api/admin/merchants")
    def merchants():
        services["require_admin"]()
        with db() as c:
            return jsonify(
                [
                    dict(r)
                    for r in c.execute("""SELECT m.login,m.created,m.profile,
                m.credits-COALESCE((SELECT SUM(h.amount) FROM credit_hold h JOIN job j ON j.id=h.job WHERE j.tenant=m.id),0) credits,
                (SELECT COUNT(*) FROM job j WHERE j.tenant=m.id) tasks,
                (SELECT COUNT(*) FROM purchase p WHERE p.tenant=m.id AND state='paid') orders,s.role FROM merchant m
                LEFT JOIN staff_role s ON s.tenant=m.id WHERE m.login IS NOT NULL ORDER BY m.created DESC""")
                ]
            )

    @app.post("/api/admin/staff")
    def assign_role():
        services["require_admin"]()
        actor, v = services["reqtenant"](), services["body"]()
        with db(True) as c:
            merchant = c.execute(
                "SELECT id FROM merchant WHERE login=?", (v.get("login"),)
            ).fetchone()
            group = v.get("role")
            if not merchant or group not in (*ROLES, ""):
                raise ValueError("请选择注册账号和有效的管理员角色。")
            c.execute("DELETE FROM staff_role WHERE tenant=?", (merchant["id"],))
            if group:
                c.execute("INSERT INTO staff_role VALUES(?,?)", (merchant["id"], group))
            audit(
                c,
                actor,
                "调整后台角色",
                dump(dict(merchant=merchant["id"], role=group)),
            )
        return jsonify(ok=True)

    @app.post("/api/admin/credits")
    def adjust():
        services["require_admin"]()
        actor, v = services["reqtenant"](), services["body"]()
        amount = v.get("amount")
        ref = services["string"](v.get("ref"), 120)
        reason = services["string"](v.get("reason"), 240)
        if (
            type(amount) is not int
            or not 0 < abs(amount) <= 1_000_000
            or not ref
            or not reason
        ):
            raise ValueError("请填写非零积分、业务单号和原因。")
        with db(True) as c:
            m = c.execute(
                "SELECT id FROM merchant WHERE login=?", (v.get("login"),)
            ).fetchone()
            if not m:
                raise ValueError("找不到商家。")
            t = m["id"]
            old = c.execute(
                "SELECT * FROM credit_adjustment WHERE tenant=? AND ref=?", (t, ref)
            ).fetchone()
            if old:
                if old["amount"] != amount or old["reason"] != reason:
                    raise ValueError("该业务单号已关联其他调整。")
                return jsonify(ok=True)
            if (
                amount > 0
                and c.execute(
                    "SELECT 1 FROM credit_event WHERE tenant=? AND job=? AND action='release'",
                    (t, ref),
                ).fetchone()
            ):
                raise ValueError("该任务已自动退回积分。")
            key = "adjust:" + t + ":" + ref
            if amount > 0:
                wallet.grant(c, t, "人工赠送或补偿 · " + reason, key, amount)
            else:
                wallet.reserve(c, t, key, -amount)
                wallet.finish(c, t, key, True)
                c.execute(
                    "UPDATE merchant SET credits=credits+? WHERE id=?", (amount, t)
                )
                c.execute(
                    "INSERT INTO ledger(tenant,job,delta,note,created) VALUES(?,?,?,?,?)",
                    (t, key, amount, "人工扣减 · " + reason, now()),
                )
            c.execute(
                "INSERT INTO credit_adjustment VALUES(?,?,?,?,?,?)",
                (t, ref, actor, amount, reason, now()),
            )
            audit(
                c,
                actor,
                "人工积分调整",
                dump(
                    {"tenant": t, "reference": ref, "amount": amount, "reason": reason}
                ),
            )
        return jsonify(ok=True)
