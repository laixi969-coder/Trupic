import datetime as dt
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from . import sealing
from .media import ROOT

DATA = Path(os.getenv("TRUPIC_DATA", ROOT / ".trupic")).resolve()
DATA.mkdir(mode=0o700, parents=True, exist_ok=True)

# Workspaces opened without an account receive trial credits up to this many times per network per day.
TRIAL_LIMIT = int(os.getenv("TRUPIC_TRIAL_PER_DAY") or 5)
TRIAL_NOTE = "同一网络今天的免费体验名额已用完，明天会恢复。也可以注册商家账号或选购套餐后继续。"


model_job = ContextVar("model_job", default=None)


def secret(name):
    p = DATA / name
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    return p.read_text().strip()


@contextmanager
def db(write=False):
    c = sqlite3.connect(DATA / "studio.sqlite3", timeout=15)
    c.row_factory = sqlite3.Row
    c.create_function("current_model_job", 0, model_job.get)
    sealing.register(c)
    try:
        if write:
            c.execute("BEGIN IMMEDIATE")
        yield c
        c.commit()
    except sqlite3.OperationalError as exc:
        c.rollback()
        raise sealing.wrap_error(exc) from None
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def now():
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def ident():
    return uuid.uuid4().hex


def dump(x):
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def audit(c, actor, action, target):
    c.execute(
        "INSERT INTO audit(actor,action,target,created) VALUES(?,?,?,?)",
        (actor, action, target, now()),
    )


def init():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS merchant(id TEXT PRIMARY KEY,login TEXT UNIQUE,password TEXT,profile TEXT NOT NULL,credits INTEGER NOT NULL DEFAULT 120,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS brand_font(id TEXT PRIMARY KEY, tenant TEXT NOT NULL, digest TEXT NOT NULL, info TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(tenant,digest));
        CREATE TABLE IF NOT EXISTS asset(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,name TEXT NOT NULL,info TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cos_object(bucket TEXT,region TEXT,key TEXT,action TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,due REAL NOT NULL DEFAULT 0,error TEXT,PRIMARY KEY(bucket,region,key));
        CREATE TABLE IF NOT EXISTS video_reference(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,name TEXT NOT NULL,analysis TEXT NOT NULL,created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS asset_tenant ON asset(tenant);
        CREATE TABLE IF NOT EXISTS job(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,request_key TEXT NOT NULL,spec TEXT NOT NULL,state TEXT NOT NULL,cost INTEGER NOT NULL,work TEXT NOT NULL,version INTEGER NOT NULL,error TEXT,created TEXT NOT NULL,UNIQUE(tenant,request_key));
        CREATE TABLE IF NOT EXISTS work(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,kind TEXT NOT NULL,current INTEGER DEFAULT 1,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS version(work TEXT NOT NULL,n INTEGER NOT NULL,spec TEXT NOT NULL,copy TEXT NOT NULL,quality TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(work,n));
        CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY,tenant TEXT NOT NULL,job TEXT UNIQUE,delta INTEGER NOT NULL,note TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS topics(tenant TEXT,week TEXT,signature TEXT,items TEXT,updated TEXT,PRIMARY KEY(tenant,week));
        CREATE TABLE IF NOT EXISTS topic_record(tenant TEXT,id TEXT,item TEXT NOT NULL,first_work TEXT,PRIMARY KEY(tenant,id));
        CREATE TABLE IF NOT EXISTS provider_reserve(day TEXT PRIMARY KEY,amount INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS provider_bill(day TEXT,platform TEXT,model TEXT,kind TEXT,currency TEXT,amount INTEGER NOT NULL,source TEXT NOT NULL,updated TEXT NOT NULL,PRIMARY KEY(day,platform,model,kind,currency));
        CREATE TABLE IF NOT EXISTS provider_usage(day TEXT,kind TEXT,calls INTEGER NOT NULL,PRIMARY KEY(day,kind));
        CREATE TABLE IF NOT EXISTS model_provider(id TEXT PRIMARY KEY,url TEXT NOT NULL,key TEXT NOT NULL,text TEXT NOT NULL,vision TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS job_bill(job TEXT PRIMARY KEY,amount INTEGER NOT NULL,source TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS model_route_version(n INTEGER PRIMARY KEY,actor TEXT NOT NULL,created TEXT NOT NULL,before_json TEXT NOT NULL,after_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS model_backup(kind TEXT PRIMARY KEY,platform TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS model_route(kind TEXT PRIMARY KEY,platform TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS model_catalog(platform TEXT,kind TEXT,signature TEXT NOT NULL,data TEXT NOT NULL,updated TEXT NOT NULL,PRIMARY KEY(platform,kind));
        CREATE TABLE IF NOT EXISTS model_call(id INTEGER PRIMARY KEY,day TEXT NOT NULL,kind TEXT NOT NULL,platform TEXT NOT NULL,model TEXT NOT NULL,ok INTEGER NOT NULL,ms INTEGER NOT NULL,input_tokens INTEGER,output_tokens INTEGER);
        CREATE INDEX IF NOT EXISTS model_call_day ON model_call(day);
        CREATE TABLE IF NOT EXISTS event(id TEXT PRIMARY KEY,title TEXT,city TEXT,starts TEXT,ends TEXT,source TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS effect(work TEXT,n INTEGER,views INTEGER,clicks INTEGER,inquiries INTEGER,visits INTEGER,source TEXT,PRIMARY KEY(work,n));
        CREATE TABLE IF NOT EXISTS downloads(work TEXT,n INTEGER,count INTEGER,PRIMARY KEY(work,n));
        CREATE TABLE IF NOT EXISTS review(work TEXT NOT NULL,n INTEGER NOT NULL,rating TEXT,tags TEXT,metrics TEXT,created TEXT,PRIMARY KEY(work,n));
        CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,title TEXT,source TEXT UNIQUE,license TEXT,kind TEXT,category TEXT,lesson TEXT,issue TEXT,status TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS rules(id TEXT PRIMARY KEY,name TEXT,method TEXT,reason TEXT,tests TEXT,status TEXT,percent INTEGER,created TEXT);
        CREATE TABLE IF NOT EXISTS skill_switch(skill TEXT PRIMARY KEY,enabled INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS skill_package(id TEXT PRIMARY KEY, definition TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS skill_version(skill TEXT NOT NULL,n INTEGER NOT NULL,instructions TEXT NOT NULL,reason TEXT NOT NULL,tests TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL,published TEXT,PRIMARY KEY(skill,n));
        CREATE UNIQUE INDEX IF NOT EXISTS skill_active_version ON skill_version(skill,status) WHERE status IN ('pilot','live');
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,target TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS trial_grant(source TEXT NOT NULL,tenant TEXT NOT NULL,created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS trial_grant_source ON trial_grant(source,created);
        """)
        for table, column, datatype in (
            ("model_call", "job", "TEXT"),
            ("model_call", "error", "TEXT"),
            ("model_call", "created", "TEXT"),
            ("model_provider", "label", "TEXT NOT NULL DEFAULT ''"),
            ("model_provider", "connections", "TEXT NOT NULL DEFAULT '{}'"),
            ("cases", "tags", "TEXT DEFAULT ''"),
            ("cases", "scenario", "TEXT DEFAULT ''"),
            ("rules", "case_id", "TEXT DEFAULT ''"),
            ("job", "worker_pid", "INTEGER"),
            ("job", "copy_checkpoint", "TEXT"),
            ("job", "visual_review", "TEXT"),
            ("job", "stage", "TEXT"),
            ("rules", "retrievable", "INTEGER NOT NULL DEFAULT 0"),
            ("event", "is_news", "INTEGER NOT NULL DEFAULT 0"),
            ("event", "feed_id", "TEXT"),
            ("event", "keywords", "TEXT NOT NULL DEFAULT ''"),
            ("event", "category", "TEXT NOT NULL DEFAULT '本地活动'"),
        ):
            if column not in [
                r["name"] for r in c.execute(f"PRAGMA table_info({table})")
            ]:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {datatype}")
        c.execute("CREATE INDEX IF NOT EXISTS model_call_job ON model_call(job)")
        sealing.open_provider_table(c)
        # Stamp each model call once the column exists, whatever wrote the row.
        c.execute("""CREATE TRIGGER IF NOT EXISTS model_call_stamp AFTER INSERT ON model_call WHEN NEW.created IS NULL
            BEGIN UPDATE model_call SET created=strftime('%Y-%m-%d %H:%M:%S','now') WHERE id=NEW.id; END""")
        from .pricing import initialize
        initialize(c)
        from . import wallet
        wallet.initialize(c)
        from .event_sources import init_sources
        init_sources(c)
        if not c.execute("SELECT 1 FROM rules LIMIT 1").fetchone():
            c.execute(
                "INSERT INTO rules(id,name,method,reason,tests,status,percent,created) VALUES(?,?,?,?,?,?,?,?)",
                (
                    "baseline",
                    "创意策略 v1",
                    "moment",
                    "初始创意策略",
                    "[]",
                    "live",
                    100,
                    now(),
                ),
            )


def trial_allowed(c, tenant, source):
    """Count one trial against the network that opened the workspace.

    A loopback address means a same-host reverse proxy whose client addresses are
    not being forwarded; it must not pool every visitor into one quota.
    """
    if not TRIAL_LIMIT or not source or source.startswith("127.") or source == "::1":
        return True
    since = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=24)).isoformat(
        timespec="seconds"
    )
    used = c.execute(
        "SELECT COUNT(*) FROM trial_grant WHERE source=? AND created>?", (source, since)
    ).fetchone()[0]
    if used >= TRIAL_LIMIT:
        return False
    c.execute(
        "INSERT INTO trial_grant(source,tenant,created) VALUES(?,?,?)",
        (source, tenant, now()),
    )
    return True


def grant_trial(c, tenant, source):
    """Give the trial once per workspace; False when the daily cap withheld it."""
    from .pricing import current
    from . import wallet

    rates = current(c)
    if c.execute(
        "SELECT 1 FROM credit_lot WHERE tenant=? AND (ref=? OR ref='opening')",
        (tenant, "trial:" + tenant),
    ).fetchone():
        return True
    if not trial_allowed(c, tenant, source):
        return False
    wallet.grant(
        c,
        tenant,
        "开通工作室体验积分",
        "trial:" + tenant,
        rates["trial"],
        wallet.after_days(rates.get("trialDays", 30)),
    )
    return True


def tenant_new(c, tenant, source=None):
    """Open a workspace. No source means it is a side effect of signing in, not a trial visit."""
    c.execute(
        "INSERT INTO merchant(id,profile,credits,created)VALUES(?,?,?,?)", (tenant, "{}", 0, now())
    )
    if source is not None:
        grant_trial(c, tenant, source)
