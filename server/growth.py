"""Invite attribution, verified merchant rewards and scoped channel sales."""

import json
from flask import abort, jsonify
from . import wallet
from .store import audit, db, dump, ident, now

DEFAULT = {
    "generateOwner": 0,
    "generateGuest": 0,
    "paidOwner": 0,
    "paidGuest": 0,
    "firstBps": 0,
    "renewBps": 0,
}


def initialize(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS promotion_code(code TEXT PRIMARY KEY,owner TEXT NOT NULL,kind TEXT NOT NULL,
        UNIQUE(owner,kind));
    CREATE TABLE IF NOT EXISTS attribution(guest TEXT PRIMARY KEY,owner TEXT NOT NULL,kind TEXT NOT NULL,
        code TEXT NOT NULL,created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS attribution_review(id TEXT PRIMARY KEY,guest TEXT NOT NULL,code TEXT NOT NULL,
        state TEXT NOT NULL,created TEXT NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS pending_attribution ON attribution_review(guest,code) WHERE state='pending';
    CREATE TABLE IF NOT EXISTS channel_agent(tenant TEXT PRIMARY KEY,kind TEXT NOT NULL,parent TEXT);
    CREATE TABLE IF NOT EXISTS verified_business(tenant TEXT PRIMARY KEY,identity TEXT UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS growth_rules(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS reward_stage(guest TEXT NOT NULL,stage TEXT NOT NULL,reference TEXT NOT NULL,
        snapshot TEXT NOT NULL,issued INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(guest,stage));
    CREATE TABLE IF NOT EXISTS commission(order_id TEXT PRIMARY KEY,owner TEXT NOT NULL,guest TEXT NOT NULL,
        cents INTEGER NOT NULL,bps INTEGER NOT NULL,amount INTEGER NOT NULL,status TEXT NOT NULL);
    """)
    c.execute("INSERT OR IGNORE INTO growth_rules VALUES(1,?)", (dump(DEFAULT),))


def rules(c):
    return json.loads(
        c.execute("SELECT value FROM growth_rules WHERE id=1").fetchone()[0]
    )


def bind(c, guest, code, new=False):
    if not code:
        return
    row = c.execute("SELECT * FROM promotion_code WHERE code=?", (code,)).fetchone()
    if not row:
        raise ValueError("推广码无效。")
    if row["owner"] == guest:
        raise ValueError("无法使用自己的推广码。")
    old = c.execute("SELECT * FROM attribution WHERE guest=?", (guest,)).fetchone()
    if old and old["code"] == code:
        return
    if not new or old:
        c.execute(
            "INSERT OR IGNORE INTO attribution_review VALUES(?,?,?,'pending',?)",
            (ident(), guest, code, now()),
        )
        audit(c, guest, "渠道归属待核查", code)
        return
    c.execute(
        "INSERT INTO attribution VALUES(?,?,?,?,?)",
        (guest, row["owner"], row["kind"], code, now()),
    )


def release_rewards(c, guest):
    for row in c.execute(
        "SELECT * FROM reward_stage WHERE guest=? AND issued=0", (guest,)
    ).fetchall():
        if (
            row["stage"] == "paid"
            and not c.execute(
                "SELECT 1 FROM purchase WHERE id=? AND state='paid'",
                (row["reference"],),
            ).fetchone()
        ):
            continue
        rule = json.loads(row["snapshot"])
        owner = rule.get("owner") or attribution(c, guest).get("owner")
        if (
            not owner
            or c.execute(
                "SELECT COUNT(*) FROM verified_business WHERE tenant IN (?,?)",
                (guest, owner),
            ).fetchone()[0]
            != 2
        ):
            continue
        for key, t in (("Owner", owner), ("Guest", guest)):
            amount = rule[row["stage"] + key]
            if amount:
                wallet.grant(
                    c,
                    t,
                    "邀请奖励",
                    "invite:" + guest + ":" + row["stage"] + ":" + key,
                    amount,
                )
        c.execute(
            "UPDATE reward_stage SET issued=1 WHERE guest=? AND stage=?",
            (guest, row["stage"]),
        )


def attribution(c, t):
    row = c.execute("SELECT owner,kind FROM attribution WHERE guest=?", (t,)).fetchone()
    return dict(row) if row else {}


def can_assist(c, agent, guest):
    return bool(
        c.execute(
            """SELECT 1 FROM attribution a JOIN channel_agent rep ON rep.tenant=a.owner
        WHERE a.guest=? AND a.kind='agent' AND (rep.tenant=? OR rep.parent=?)""",
            (guest, agent, agent),
        ).fetchone()
    )


def milestone(c, t, stage, ref, cents=None, relation=None, sale_rules=None):
    row = attribution(c, t) if relation is None else relation
    if not row:
        return
    rule = sale_rules if sale_rules is not None else rules(c)
    if row["kind"] == "merchant":
        c.execute(
            "INSERT OR IGNORE INTO reward_stage(guest,stage,reference,snapshot) VALUES(?,?,?,?)",
            (t, stage, ref, dump({**rule, "owner": row["owner"]})),
        )
        release_rewards(c, t)
    elif stage == "paid":
        renew = c.execute(
            "SELECT 1 FROM purchase WHERE tenant=? AND id<>? AND state='paid'", (t, ref)
        ).fetchone()
        rate = rule["renewBps" if renew else "firstBps"]
        c.execute(
            "INSERT OR IGNORE INTO commission VALUES(?,?,?,?,?,?,'pending')",
            (ref, row["owner"], t, cents, rate, cents * rate // 10000),
        )


def register(app, services):
    with db() as c:
        initialize(c)

    @app.post("/api/promotion/claim")
    def claim():
        t, v = services["reqtenant"](), services["body"]()
        with db(True) as c:
            if not c.execute("SELECT login FROM merchant WHERE id=?", (t,)).fetchone()[
                0
            ]:
                raise ValueError("请先绑定账号。")
            bind(c, t, services["string"](v.get("code"), 64))
        return jsonify(ok=True)

    @app.get("/api/promotion/<code>/qr")
    def qr(code):
        import io, qrcode
        from flask import request, send_file
        from urllib.parse import urlencode

        t = services["reqtenant"]()
        with db() as c:
            if not c.execute(
                "SELECT 1 FROM promotion_code WHERE code=? AND owner=?", (code, t)
            ).fetchone():
                abort(404)
        stream = io.BytesIO()
        qrcode.make(request.url_root + "?" + urlencode({"invite": code})).save(
            stream, format="PNG"
        )
        stream.seek(0)
        return send_file(stream, mimetype="image/png")

    @app.get("/api/promotion")
    def promotion():
        t = services["reqtenant"]()
        with db(True) as c:
            if not c.execute("SELECT login FROM merchant WHERE id=?", (t,)).fetchone()[
                0
            ]:
                return jsonify(codes={}, clients=[], commissions=[])
            agency = c.execute(
                "SELECT * FROM channel_agent WHERE tenant=?", (t,)
            ).fetchone()
            codes = {}
            for k in ("merchant", "agent") if agency else ("merchant",):
                c.execute(
                    "INSERT OR IGNORE INTO promotion_code VALUES(?,?,?)",
                    (ident(), t, k),
                )
                codes[k] = c.execute(
                    "SELECT code FROM promotion_code WHERE owner=? AND kind=?", (t, k)
                ).fetchone()[0]
            scope = [t]
            if agency:
                scope.extend(
                    r[0]
                    for r in c.execute(
                        "SELECT tenant FROM channel_agent WHERE parent=?", (t,)
                    )
                )
            marks = ",".join("?" for _ in scope)
            clients = (
                [
                    dict(r)
                    for r in c.execute(
                        f"""SELECT m.login,a.kind,a.created FROM attribution a
                JOIN merchant m ON m.id=a.guest WHERE a.owner IN ({marks}) AND a.kind='agent'""",
                        scope,
                    )
                ]
                if agency
                else []
            )
            sales = (
                [
                    dict(r)
                    for r in c.execute(
                        f"""SELECT order_id,cents,bps,amount,status,m.login FROM commission
                JOIN merchant m ON m.id=commission.guest WHERE owner IN ({marks})""",
                        scope,
                    )
                ]
                if agency
                else []
            )
            assigned = (
                [
                    dict(r)
                    for r in c.execute(
                        "SELECT c.code,o.name,c.discount,c.ends FROM coupon c JOIN plan_offer o ON o.id=c.offer WHERE c.agent=? AND c.ends>=?",
                        (t, now()[:10]),
                    )
                ]
                if agency
                else []
            )
            return jsonify(
                codes=codes,
                clients=clients,
                commissions=sales,
                coupons=assigned,
                role=agency["kind"] if agency else None,
            )

    @app.route("/api/admin/growth", methods=["GET", "POST"])
    def manage():
        from flask import request

        services["require_admin"]()
        actor = services["reqtenant"]()
        with db(request.method == "POST") as c:
            if request.method == "POST":
                v = services["body"]()
                action = v.get("action")
                if action == "rules":
                    values = {k: v.get(k) for k in DEFAULT}
                    if any(
                        type(n) is not int or not 0 <= n <= 10000
                        for n in values.values()
                    ):
                        raise ValueError("奖励与费率必须为 0 到 10000 之间的整数。")
                    c.execute(
                        "UPDATE growth_rules SET value=? WHERE id=1", (dump(values),)
                    )
                    target = dump(values)
                elif action in ("verify", "agent"):
                    login = services["string"](v.get("login"), 64).lower()
                    m = c.execute(
                        "SELECT id FROM merchant WHERE login=?", (login,)
                    ).fetchone()
                    if not m:
                        raise ValueError("找不到已注册账号。")
                    target = m["id"]
                    if action == "verify":
                        identity = services["string"](v.get("identity"), 120)
                        if not identity:
                            raise ValueError("请填写已核实的唯一商户编号。")
                        used = c.execute(
                            "SELECT tenant FROM verified_business WHERE identity=?",
                            (identity,),
                        ).fetchone()
                        if used and used["tenant"] != target:
                            raise ValueError("该商户编号已绑定。")
                        retained = c.execute(
                            "SELECT identity FROM verified_business WHERE tenant=?",
                            (target,),
                        ).fetchone()
                        if retained and retained[0] != identity:
                            raise ValueError("此账号已绑定核实商户编号。")
                        c.execute(
                            "INSERT OR IGNORE INTO verified_business VALUES(?,?)",
                            (target, identity),
                        )
                        for rel in c.execute(
                            "SELECT guest FROM attribution WHERE guest=? OR owner=?",
                            (target, target),
                        ).fetchall():
                            release_rewards(c, rel["guest"])
                    else:
                        kind = v.get("role")
                        if kind not in ("个人推广员", "团队负责人", "区县代理"):
                            raise ValueError("请选择渠道角色。")
                        parent = None
                        if v.get("parent"):
                            row = c.execute(
                                """SELECT a.tenant FROM channel_agent a JOIN merchant m ON m.id=a.tenant
                                WHERE m.login=? AND a.parent IS NULL AND a.kind!='个人推广员'""",
                                (v["parent"],),
                            ).fetchone()
                            if (
                                not row
                                or row[0] == target
                                or kind != "个人推广员"
                                or c.execute(
                                    "SELECT 1 FROM channel_agent WHERE parent=?",
                                    (target,),
                                ).fetchone()
                            ):
                                raise ValueError("请选择有效的上级团队或区县代理。")
                            parent = row[0]
                        c.execute(
                            "INSERT INTO channel_agent VALUES(?,?,?) ON CONFLICT(tenant) DO UPDATE SET kind=excluded.kind,parent=excluded.parent",
                            (target, kind, parent),
                        )
                elif action in ("approve-transfer", "reject-transfer"):
                    target = services["string"](v.get("id"), 64)
                    row = c.execute(
                        """SELECT r.*,p.owner,p.kind FROM attribution_review r JOIN promotion_code p
                        ON p.code=r.code WHERE r.id=? AND r.state='pending'""",
                        (target,),
                    ).fetchone()
                    if not row:
                        raise ValueError("找不到待核查记录。")
                    if action == "approve-transfer":
                        if row["kind"] != "agent" or row["guest"] == row["owner"]:
                            raise ValueError("人工迁移仅支持有效渠道归属。")
                        old = c.execute(
                            "SELECT owner FROM attribution WHERE guest=?",
                            (row["guest"],),
                        ).fetchone()
                        c.execute(
                            """INSERT INTO attribution VALUES(?,?,?,?,?) ON CONFLICT(guest) DO UPDATE SET
                            owner=excluded.owner,kind=excluded.kind,code=excluded.code,created=excluded.created""",
                            (
                                row["guest"],
                                row["owner"],
                                row["kind"],
                                row["code"],
                                now(),
                            ),
                        )
                        audit(
                            c,
                            actor,
                            "迁移后续渠道归属",
                            dump(
                                {
                                    "guest": row["guest"],
                                    "from": old[0] if old else None,
                                    "to": row["owner"],
                                }
                            ),
                        )
                    c.execute(
                        "UPDATE attribution_review SET state=? WHERE id=?",
                        (action, target),
                    )
                elif action == "settle":
                    target = services["string"](v.get("order"), 64)
                    if not c.execute(
                        "UPDATE commission SET status='settled' WHERE order_id=? AND status='pending'",
                        (target,),
                    ).rowcount:
                        raise ValueError("无可登记的待结算佣金。")
                else:
                    raise ValueError("无效操作。")
                audit(c, actor, "渠道管理 " + action, target)
            return jsonify(
                rules=rules(c),
                reviews=[
                    dict(r)
                    for r in c.execute("""SELECT r.id,m.login guest,p.kind,a.login owner
                FROM attribution_review r JOIN promotion_code p ON p.code=r.code JOIN merchant m ON m.id=r.guest
                JOIN merchant a ON a.id=p.owner WHERE r.state='pending' ORDER BY r.created""")
                ],
                commissions=[
                    dict(r)
                    for r in c.execute(
                        "SELECT * FROM commission ORDER BY rowid DESC LIMIT 200"
                    )
                ],
            )
