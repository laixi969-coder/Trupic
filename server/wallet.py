"""Credit lots and per-attempt reservations, in the same transaction as each job."""

import datetime as dt

from .store import now


def initialize(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS credit_lot(id INTEGER PRIMARY KEY,tenant TEXT NOT NULL,source TEXT NOT NULL,
        ref TEXT NOT NULL,remaining INTEGER NOT NULL CHECK(remaining>=0),expires TEXT, UNIQUE(tenant,ref));
    CREATE INDEX IF NOT EXISTS credit_expiry ON credit_lot(tenant,expires);
    CREATE TABLE IF NOT EXISTS credit_hold(job TEXT NOT NULL,lot INTEGER NOT NULL,amount INTEGER NOT NULL,
        PRIMARY KEY(job,lot));
    CREATE TABLE IF NOT EXISTS credit_event(id INTEGER PRIMARY KEY,tenant TEXT NOT NULL,job TEXT NOT NULL,
        lot INTEGER NOT NULL,action TEXT NOT NULL,amount INTEGER NOT NULL,created TEXT NOT NULL);
    CREATE TRIGGER IF NOT EXISTS ledger_no_edit BEFORE UPDATE ON ledger BEGIN SELECT RAISE(ABORT,'immutable ledger'); END;
    CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger BEGIN SELECT RAISE(ABORT,'immutable ledger'); END;
    CREATE TRIGGER IF NOT EXISTS event_no_edit BEFORE UPDATE ON credit_event BEGIN SELECT RAISE(ABORT,'immutable ledger'); END;
    CREATE TRIGGER IF NOT EXISTS event_no_delete BEFORE DELETE ON credit_event BEGIN SELECT RAISE(ABORT,'immutable ledger'); END;
    """)
    # Pre-lot balances have no recorded expiry. Preserve that entitlement on upgrade.
    c.execute("BEGIN IMMEDIATE")
    for row in c.execute("""SELECT id,credits FROM merchant WHERE NOT EXISTS
        (SELECT 1 FROM credit_lot WHERE tenant=merchant.id)""").fetchall():
        c.execute(
            "INSERT INTO credit_lot(tenant,source,ref,remaining) VALUES(?,?,?,?)",
            (row["id"], "历史余额", "opening", row["credits"]),
        )
        for j in c.execute(
            "SELECT id,cost FROM job WHERE tenant=? AND state IN ('queued','running') ORDER BY rowid",
            (row["id"],),
        ).fetchall():
            reserve(c, row["id"], j["id"], j["cost"])


def after_days(days):
    return (dt.datetime.now(dt.UTC) + dt.timedelta(days=days)).isoformat(
        timespec="seconds"
    )


def grant(c, t, category, ref, amount, expiry=None):
    if type(amount) is not int or amount < 0:
        raise ValueError("无效积分数量。")
    row = c.execute(
        """INSERT INTO credit_lot(tenant,source,ref,remaining,expires) VALUES(?,?,?,?,?)
        ON CONFLICT(tenant,ref) DO NOTHING""",
        (t, category, ref, amount, expiry),
    )
    if row.rowcount:
        c.execute("UPDATE merchant SET credits=credits+? WHERE id=?", (amount, t))
        c.execute(
            "INSERT INTO ledger(tenant,job,delta,note,created) VALUES(?,?,?,?,?)",
            (t, ref, amount, category, now()),
        )
    return bool(row.rowcount)


def expire(c, t):
    for lot in c.execute(
        "SELECT * FROM credit_lot WHERE tenant=? AND expires<=? AND remaining>0",
        (t, now()),
    ).fetchall():
        amount = lot["remaining"]
        c.execute("UPDATE credit_lot SET remaining=0 WHERE id=?", (lot["id"],))
        c.execute("UPDATE merchant SET credits=credits-? WHERE id=?", (amount, t))
        c.execute(
            "INSERT INTO ledger(tenant,delta,note,created) VALUES(?,?,?,?)",
            (t, -amount, "积分到期 · " + lot["ref"], now()),
        )


def event(c, t, job, lot, action, amount):
    c.execute(
        "INSERT INTO credit_event(tenant,job,lot,action,amount,created) VALUES(?,?,?,?,?,?)",
        (t, job, lot, action, amount, now()),
    )


def reserve(c, t, job, amount):
    expire(c, t)
    for lot in c.execute(
        """SELECT id,remaining FROM credit_lot WHERE tenant=? AND remaining>0
        ORDER BY expires IS NULL,expires,id""",
        (t,),
    ).fetchall():
        if not amount:
            break
        use = min(amount, lot["remaining"])
        c.execute(
            "UPDATE credit_lot SET remaining=remaining-? WHERE id=?", (use, lot["id"])
        )
        c.execute("INSERT INTO credit_hold VALUES(?,?,?)", (job, lot["id"], use))
        event(c, t, job, lot["id"], "reserve", use)
        amount -= use
    if amount:
        raise ValueError("可用积分不足。")


def finish(c, t, job, success):
    for row in c.execute("SELECT * FROM credit_hold WHERE job=?", (job,)).fetchall():
        if not success:
            c.execute(
                "UPDATE credit_lot SET remaining=remaining+? WHERE id=?",
                (row["amount"], row["lot"]),
            )
        event(c, t, job, row["lot"], "consume" if success else "release", row["amount"])
    c.execute("DELETE FROM credit_hold WHERE job=?", (job,))
    expire(c, t)
