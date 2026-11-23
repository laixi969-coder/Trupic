"""Invite attribution, verified merchant rewards and scoped channel sales."""

import datetime as dt
import json
from flask import abort, jsonify
from . import wallet
from .store import audit, db, dump, ident, now

AMOUNTS = {
    "generateOwner": 0,
    "generateGuest": 0,
    "paidOwner": 0,
    "paidGuest": 0,
    "firstBps": 0,
    "renewBps": 0,
}


DEFAULT = {
    **AMOUNTS,
    "starts": "",
    "ends": "",
    "overlap": "agent",
    "settleDays": 0,
    "renewMonths": 0,
}


def checked_rules(payload, previous):
    values = {key: payload.get(key, previous[key]) for key in DEFAULT}
    if any(type(values[k]) is not int or not 0 <= values[k] <= 10000 for k in AMOUNTS):
        raise ValueError("奖励与费率必须为 0 到 10000 之间的整数。")
    if any(
        type(values[k]) is not int or not 0 <= values[k] <= 3650
        for k in ("settleDays", "renewMonths")
    ):
        raise ValueError("结算等待天数及续费分佣月数须为 0–3650 的整数。")
    if values["overlap"] not in ("agent", "merchant", "both"):
        raise ValueError("请选择有效的归属优先规则。")
    for key in ("starts", "ends"):
        if values[key] != "":
            try:
                values[key] = dt.date.fromisoformat(values[key]).isoformat()
            except (ValueError, TypeError):
                raise ValueError("请填写有效的活动日期。")
    if values["ends"] and values["starts"] > values["ends"]:
        raise ValueError("活动结束日期须在开始日期之后。")
    return values


def initialize(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS promotion_code(code TEXT PRIMARY KEY,owner TEXT NOT NULL,kind TEXT NOT NULL,
        UNIQUE(owner,kind));
    CREATE TABLE IF NOT EXISTS attribution(guest TEXT NOT NULL,owner TEXT NOT NULL,kind TEXT NOT NULL,
        code TEXT NOT NULL,created TEXT NOT NULL, PRIMARY KEY(guest,kind));
    CREATE TABLE IF NOT EXISTS attribution_review(id TEXT PRIMARY KEY,guest TEXT NOT NULL,code TEXT NOT NULL,
        state TEXT NOT NULL,created TEXT NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS pending_attribution ON attribution_review(guest,code) WHERE state='pending';
    CREATE TABLE IF NOT EXISTS channel_agent(tenant TEXT PRIMARY KEY,kind TEXT NOT NULL,parent TEXT);
    CREATE TABLE IF NOT EXISTS verified_business(tenant TEXT PRIMARY KEY,identity TEXT UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS growth_rules(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS growth_rule_version(n INTEGER PRIMARY KEY, value TEXT NOT NULL, created TEXT NOT NULL, actor TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS reward_stage(guest TEXT NOT NULL,stage TEXT NOT NULL,reference TEXT NOT NULL,
        snapshot TEXT NOT NULL,issued INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(guest,stage));
    CREATE TABLE IF NOT EXISTS commission(order_id TEXT PRIMARY KEY,owner TEXT NOT NULL,guest TEXT NOT NULL,
        cents INTEGER NOT NULL,bps INTEGER NOT NULL,amount INTEGER NOT NULL,status TEXT NOT NULL);
    """)
    c.execute("BEGIN IMMEDIATE")
    # Preserve both the original timestamps and pre-migration order snapshots.
    if not any(
        r["name"] == "kind" and r["pk"]
        for r in c.execute("PRAGMA table_info(attribution)")
    ):
        c.execute("ALTER TABLE attribution RENAME TO attribution_legacy")
        c.execute("""CREATE TABLE attribution(guest TEXT NOT NULL, owner TEXT NOT NULL, kind TEXT NOT NULL,
                    code TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(guest,kind))""")
        c.execute("INSERT INTO attribution SELECT * FROM attribution_legacy")
        c.execute("DROP TABLE attribution_legacy")
    c.execute("CREATE INDEX IF NOT EXISTS attribution_owner ON attribution(owner,kind)")
    if not any(r["name"] == "team" for r in c.execute("PRAGMA table_info(commission)")):
        c.execute("ALTER TABLE commission ADD COLUMN team TEXT")
        c.execute(
            """UPDATE commission SET team=(SELECT parent FROM channel_agent WHERE tenant=commission.owner)"""
        )
    if "available" not in {
        r["name"] for r in c.execute("PRAGMA table_info(commission)")
    }:
        c.execute("ALTER TABLE commission ADD COLUMN available TEXT")
    if "enabled" not in {
        r["name"] for r in c.execute("PRAGMA table_info(channel_agent)")
    }:
        c.execute(
            "ALTER TABLE channel_agent ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
        )
    c.execute("INSERT OR IGNORE INTO growth_rules VALUES(1,?)", (dump(DEFAULT),))
    c.execute(
        """INSERT OR IGNORE INTO growth_rule_version SELECT 1,value,?,'migration'
        FROM growth_rules WHERE id=1""",
        (now(),),
    )


def rules(c):
    row = c.execute(
        "SELECT n,value FROM growth_rule_version ORDER BY n DESC LIMIT 1"
    ).fetchone()
    return DEFAULT | json.loads(row["value"]) | {"version": row["n"]}


def check_cycle(c, guest, owner):
    cycle = c.execute(
        """WITH RECURSIVE upstream(id) AS (
        SELECT ? UNION SELECT a.owner FROM attribution a JOIN upstream u ON a.guest=u.id
    ) SELECT 1 FROM upstream WHERE id=?""",
        (owner, guest),
    ).fetchone()
    if cycle:
        raise ValueError("该推广关系会形成循环。")


def bind(c, guest, code, new=False, expected=None):
    if not code:
        return
    row = c.execute("SELECT * FROM promotion_code WHERE code=?", (code,)).fetchone()
    if not row or (expected and row["kind"] != expected):
        raise ValueError("推广码无效或用途不符。")
    if (
        row["kind"] == "agent"
        and not c.execute(
            "SELECT 1 FROM channel_agent WHERE tenant=? AND enabled=1", (row["owner"],)
        ).fetchone()
    ):
        raise ValueError("该渠道推广码已停用。")
    if row["owner"] == guest:
        raise ValueError("无法使用自己的推广码。")
    old = c.execute(
        "SELECT * FROM attribution WHERE guest=? AND kind=?", (guest, row["kind"])
    ).fetchone()
    if old and old["code"] == code:
        return
    if not new or old:
        c.execute(
            "INSERT OR IGNORE INTO attribution_review VALUES(?,?,?,'pending',?)",
            (ident(), guest, code, now()),
        )
        if c.execute("SELECT changes()").fetchone()[0]:
            audit(c, guest, "渠道归属待核查", code)
        return
    check_cycle(c, guest, row["owner"])
    c.execute(
        "INSERT INTO attribution VALUES(?,?,?,?,?)",
        (guest, row["owner"], row["kind"], code, now()),
    )


def combined_channel(c, owner):
    own = c.execute(
        "SELECT p.code FROM promotion_code p JOIN channel_agent a ON a.tenant=p.owner WHERE p.owner=? AND p.kind='agent' AND a.enabled=1",
        (owner,),
    ).fetchone()
    inherited = c.execute(
        "SELECT r.code FROM attribution r JOIN channel_agent a ON a.tenant=r.owner WHERE r.guest=? AND r.kind='agent' AND a.enabled=1",
        (owner,),
    ).fetchone()
    return (own or inherited or [""])[0]


def bind_link(c, guest, invite, channel, new=False):
    if channel:
        source = c.execute(
            "SELECT owner FROM promotion_code WHERE code=? AND kind='merchant'",
            (invite,),
        ).fetchone()
        if not source or combined_channel(c, source["owner"]) != channel:
            raise ValueError("联合推广链接的渠道归属已变更，请获取新链接。")
    bind(c, guest, invite, new)
    if channel:
        bind(c, guest, channel, new, expected="agent")


def release_rewards(c, guest):
    for row in c.execute(
        "SELECT * FROM reward_stage WHERE guest=? AND issued=0", (guest,)
    ).fetchall():
        if (
            row["stage"] == "paid"
            and not c.execute(
                "SELECT 1 FROM purchase WHERE id=? AND state='paid' AND NOT EXISTS (SELECT 1 FROM payment_review pr WHERE pr.order_id=purchase.id AND pr.state!='approved')",
                (row["reference"],),
            ).fetchone()
        ):
            continue
        rule = json.loads(row["snapshot"])
        owner = rule.get("owner") or attribution(c, guest).get("merchant")
        if rule.get("eligible") is False:
            continue
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
    rows = c.execute(
        """SELECT a.kind,a.owner,rep.parent FROM attribution a
        LEFT JOIN channel_agent rep ON rep.tenant=a.owner WHERE a.guest=? AND (a.kind!='agent' OR rep.enabled=1)""",
        (t,),
    )
    result = {}
    for row in rows:
        result[row["kind"]] = row["owner"]
        if row["kind"] == "agent":
            result["team"] = row["parent"]
    return result


def can_assist(c, agent, guest):
    return bool(
        c.execute(
            """SELECT 1 FROM attribution a JOIN channel_agent rep ON rep.tenant=a.owner
        JOIN channel_agent actor ON actor.tenant=? AND actor.enabled=1
        WHERE a.guest=? AND a.kind='agent' AND rep.enabled=1 AND (rep.tenant=actor.tenant OR rep.parent=actor.tenant)""",
            (agent, guest),
        ).fetchone()
    )


def milestone(c, t, stage, ref, cents=None, relation=None, sale_rules=None):
    row = attribution(c, t) if relation is None else relation
    if not row:
        return
    rule = sale_rules if sale_rules is not None else rules(c)
    if "kind" in row:  # Orders quoted by V3.0 contained a single attribution.
        row = {row["kind"]: row["owner"]}
    rule = DEFAULT | rule
    day = now()[:10]
    active = rule["starts"] <= day and (not rule["ends"] or day <= rule["ends"])
    reward = bool(
        row.get("merchant")
        and active
        and (not row.get("agent") or rule["overlap"] != "agent")
    )
    if row.get("merchant"):
        c.execute(
            "INSERT OR IGNORE INTO reward_stage(guest,stage,reference,snapshot) VALUES(?,?,?,?)",
            (
                t,
                stage,
                ref,
                dump({**rule, "owner": row["merchant"], "eligible": reward}),
            ),
        )
        release_rewards(c, t)
    if stage == "paid" and row.get("agent"):
        renew = c.execute(
            "SELECT MIN(paid) FROM purchase WHERE tenant=? AND id<>? AND paid IS NOT NULL HAVING COUNT(*)>0",
            (t, ref),
        ).fetchone()
        if not renew and reward and rule["overlap"] == "merchant":
            return
        if renew and rule["renewMonths"]:
            from .commerce import month_after

            if now() >= month_after(renew[0], rule["renewMonths"]):
                return
        available = (
            dt.datetime.fromisoformat(now()) + dt.timedelta(days=rule["settleDays"])
        ).isoformat(timespec="seconds")
        rate = rule["renewBps" if renew else "firstBps"]
        c.execute(
            "INSERT OR IGNORE INTO commission(order_id,owner,guest,cents,bps,amount,status,team,available) VALUES(?,?,?,?,?,?,'pending',?,?)",
            (
                ref,
                row["agent"],
                t,
                cents,
                rate,
                cents * rate // 10000,
                row.get("team"),
                available,
            ),
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
            bind_link(
                c,
                t,
                services["string"](v.get("code"), 64),
                services["string"](v.get("channel"), 64),
            )
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
            params = {"invite": code}
            if request.args.get("channel"):
                channel = combined_channel(c, t)
                if (
                    request.args["channel"] != channel
                    or not c.execute(
                        "SELECT 1 FROM promotion_code WHERE code=? AND kind='merchant'",
                        (code,),
                    ).fetchone()
                ):
                    abort(400)
                params["channel"] = channel
        stream = io.BytesIO()
        qrcode.make(request.url_root + "?" + urlencode(params)).save(
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
                "SELECT * FROM channel_agent WHERE tenant=? AND enabled=1", (t,)
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
                        f"""SELECT m.login,a.kind,a.created,rep.login representative FROM attribution a JOIN merchant rep ON rep.id=a.owner
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
                        """SELECT order_id,cents,bps,amount,status,available,m.login FROM commission
                JOIN merchant m ON m.id=commission.guest WHERE owner=? OR team=? ORDER BY commission.rowid DESC""",
                        (t, t),
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
                invites=[
                    dict(r)
                    for r in c.execute(
                        """SELECT m.login,a.created,
                    (SELECT COUNT(*) FROM reward_stage s WHERE s.guest=a.guest AND s.issued=1
                     AND json_extract(s.snapshot,'$.owner')=a.owner) rewardedStages
                    FROM attribution a JOIN merchant m ON m.id=a.guest
                    WHERE a.owner=? AND a.kind='merchant' ORDER BY a.created DESC""",
                        (t,),
                    )
                ],
                team=[
                    dict(r)
                    for r in c.execute(
                        """SELECT m.login,a.kind FROM channel_agent a
                    JOIN merchant m ON m.id=a.tenant WHERE a.parent=? AND a.enabled=1 ORDER BY m.login""",
                        (t,),
                    )
                ],
                asOf=now(),
                channel=combined_channel(c, t),
                campaign={
                    key: value
                    for key, value in rules(c).items()
                    if key
                    in (
                        "starts",
                        "ends",
                        "generateOwner",
                        "generateGuest",
                        "paidOwner",
                        "paidGuest",
                    )
                },
                rewards=[
                    dict(r)
                    for r in c.execute(
                        """SELECT m.login,s.stage,s.issued,
                    json_extract(s.snapshot,'$.eligible') eligible,
                    json_extract(s.snapshot,'$.'||s.stage||CASE WHEN s.guest=? THEN 'Guest' ELSE 'Owner' END) amount,
                    p.state payment FROM reward_stage s JOIN merchant m ON m.id=s.guest
                    LEFT JOIN purchase p ON s.stage='paid' AND p.id=s.reference
                    WHERE s.guest=? OR json_extract(s.snapshot,'$.owner')=? ORDER BY s.rowid DESC""",
                        (t, t, t),
                    )
                ],
                orders=[
                    dict(r)
                    for r in c.execute(
                        """SELECT p.id,p.cents,p.created,p.state,m.login,
                    json_extract(p.snapshot,'$.name') name FROM purchase p JOIN merchant m ON m.id=p.tenant
                    LEFT JOIN commission cm ON cm.order_id=p.id
                    WHERE cm.owner=? OR cm.team=? OR json_extract(p.snapshot,'$.attribution.agent')=?
                    OR json_extract(p.snapshot,'$.attribution.team')=? OR
                    (json_extract(p.snapshot,'$.attribution.kind')='agent' AND json_extract(p.snapshot,'$.attribution.owner')=?)
                    ORDER BY p.created DESC,p.rowid DESC""",
                        (t,) * 5,
                    )
                ]
                if agency
                else [],
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
                    previous = rules(c)
                    if (
                        "expectedVersion" in v
                        and v["expectedVersion"] != previous["version"]
                    ):
                        raise ValueError("活动规则已更新，请重新载入后再保存。")
                    values = checked_rules(v, previous)
                    c.execute(
                        "INSERT INTO growth_rule_version(value,created,actor) VALUES(?,?,?)",
                        (dump(values), now(), actor),
                    )
                    c.execute(
                        "UPDATE growth_rules SET value=? WHERE id=1", (dump(values),)
                    )
                    target = dump({"before": previous, "after": values})
                elif action == "disable-agent":
                    login = services["string"](v.get("login"), 64).lower()
                    if not c.execute(
                        """UPDATE channel_agent SET enabled=0 WHERE enabled=1 AND tenant=
                        (SELECT id FROM merchant WHERE login=?)""",
                        (login,),
                    ).rowcount:
                        raise ValueError("找不到当前有效的渠道账号。")
                    target = login
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
                        if (
                            kind == "个人推广员"
                            and c.execute(
                                "SELECT 1 FROM channel_agent WHERE parent=?", (target,)
                            ).fetchone()
                        ):
                            raise ValueError("请先迁移下属推广员。")
                        parent = None
                        if v.get("parent"):
                            row = c.execute(
                                """SELECT a.tenant FROM channel_agent a JOIN merchant m ON m.id=a.tenant
                                WHERE m.login=? AND a.enabled=1 AND a.parent IS NULL AND a.kind!='个人推广员'""",
                                (v["parent"].strip().lower(),),
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
                            "INSERT INTO channel_agent(tenant,kind,parent) VALUES(?,?,?) ON CONFLICT(tenant) DO UPDATE SET kind=excluded.kind,parent=excluded.parent,enabled=1",
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
                        if not c.execute(
                            "SELECT 1 FROM channel_agent WHERE tenant=? AND enabled=1",
                            (row["owner"],),
                        ).fetchone():
                            raise ValueError("此渠道授权已停用。")
                        check_cycle(c, row["guest"], row["owner"])
                        old = c.execute(
                            "SELECT owner FROM attribution WHERE guest=? AND kind='agent'",
                            (row["guest"],),
                        ).fetchone()
                        c.execute(
                            """INSERT INTO attribution VALUES(?,?,?,?,?) ON CONFLICT(guest,kind) DO UPDATE SET
                            owner=excluded.owner,kind=excluded.kind,code=excluded.code,created=excluded.created""",
                            (
                                row["guest"],
                                row["owner"],
                                row["kind"],
                                row["code"],
                                now(),
                            ),
                        )
                        c.execute(
                            """UPDATE attribution_review SET state='superseded' WHERE guest=? AND id<>?
                            AND state='pending' AND code IN (SELECT code FROM promotion_code WHERE kind='agent')""",
                            (row["guest"], target),
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
                elif action in ("verify-payer", "reject-payer"):
                    target = services["string"](v.get("order"), 64)
                    evidence = services["string"](v.get("reference"), 120)
                    if not evidence:
                        raise ValueError("请填写实际付款核对依据。")
                    approved = action == "verify-payer"
                    if not c.execute(
                        "UPDATE payment_review SET state=? WHERE order_id=? AND state='pending'",
                        ("approved" if approved else "rejected", target),
                    ).rowcount:
                        raise ValueError("找不到待核对的支付记录。")
                    c.execute(
                        "UPDATE commission SET status=? WHERE order_id=? AND status='payer_review'",
                        ("pending" if approved else "disqualified", target),
                    )
                    if approved:
                        guest = c.execute(
                            "SELECT tenant FROM purchase WHERE id=?", (target,)
                        ).fetchone()[0]
                        release_rewards(c, guest)
                    target = dump({"order": target, "reference": evidence})
                elif action == "recover":
                    target = services["string"](v.get("order"), 64)
                    reference = services["string"](v.get("reference"), 120)
                    if not reference:
                        raise ValueError("请填写实际追回的凭证。")
                    if not c.execute(
                        "UPDATE commission SET status='recovered' WHERE order_id=? AND status='recovery_due'",
                        (target,),
                    ).rowcount:
                        raise ValueError("找不到待追回佣金。")
                    target = dump({"order": target, "reference": reference})
                elif action == "settle":
                    target = services["string"](v.get("order"), 64)
                    if not c.execute(
                        "UPDATE commission SET status='settled' WHERE order_id=? AND status='pending' AND (available IS NULL OR available<=?)",
                        (target, now()),
                    ).rowcount:
                        raise ValueError("无可登记的待结算佣金。")
                else:
                    raise ValueError("无效操作。")
                audit(c, actor, "渠道管理 " + action, target)
            return jsonify(
                asOf=now(),
                rules=rules(c),
                agents=[
                    dict(r)
                    for r in c.execute("""SELECT m.login,a.kind,a.enabled,p.login parent
                    FROM channel_agent a JOIN merchant m ON m.id=a.tenant
                    LEFT JOIN merchant p ON p.id=a.parent ORDER BY m.login""")
                ],
                payments=[
                    dict(r)
                    for r in c.execute("""SELECT p.id,p.payer,p.payer_login,p.cents,m.login,pr.reason
                    FROM payment_review pr JOIN purchase p ON p.id=pr.order_id JOIN merchant m ON m.id=p.tenant
                    WHERE pr.state='pending' ORDER BY p.paid""")
                ],
                reviews=[
                    dict(r)
                    for r in c.execute("""SELECT r.id,m.login guest,p.kind,a.login owner
                FROM attribution_review r JOIN promotion_code p ON p.code=r.code JOIN merchant m ON m.id=r.guest
                JOIN merchant a ON a.id=p.owner WHERE r.state='pending' ORDER BY r.created""")
                ],
                commissions=[
                    dict(r)
                    for r in c.execute(
                        """SELECT cm.*,p.payer,p.payer_login, initiator.login initiator, rep.login representative,
                        m.login merchant FROM commission cm JOIN purchase p ON p.id=cm.order_id
                        JOIN merchant m ON m.id=cm.guest JOIN merchant rep ON rep.id=cm.owner
                        LEFT JOIN merchant initiator ON initiator.id=json_extract(p.snapshot,'$.initiator')
                        ORDER BY cm.rowid DESC"""
                    )
                ],
            )
