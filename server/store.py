import datetime as dt
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .media import ROOT

DATA = Path(os.getenv("TRUPIC_DATA", ROOT / ".trupic")).resolve()
DATA.mkdir(mode=0o700, parents=True, exist_ok=True)


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
    try:
        if write:
            c.execute("BEGIN IMMEDIATE")
        yield c
        c.commit()
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
        CREATE INDEX IF NOT EXISTS asset_tenant ON asset(tenant);
        CREATE TABLE IF NOT EXISTS job(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,request_key TEXT NOT NULL,spec TEXT NOT NULL,state TEXT NOT NULL,cost INTEGER NOT NULL,work TEXT NOT NULL,version INTEGER NOT NULL,error TEXT,created TEXT NOT NULL,UNIQUE(tenant,request_key));
        CREATE TABLE IF NOT EXISTS work(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,kind TEXT NOT NULL,current INTEGER DEFAULT 1,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS version(work TEXT NOT NULL,n INTEGER NOT NULL,spec TEXT NOT NULL,copy TEXT NOT NULL,quality TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(work,n));
        CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY,tenant TEXT NOT NULL,job TEXT UNIQUE,delta INTEGER NOT NULL,note TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS topics(tenant TEXT,week TEXT,signature TEXT,items TEXT,updated TEXT,PRIMARY KEY(tenant,week));
        CREATE TABLE IF NOT EXISTS topic_record(tenant TEXT,id TEXT,item TEXT NOT NULL,first_work TEXT,PRIMARY KEY(tenant,id));
        CREATE TABLE IF NOT EXISTS provider_usage(day TEXT,kind TEXT,calls INTEGER NOT NULL,PRIMARY KEY(day,kind));
        CREATE TABLE IF NOT EXISTS model_provider(id TEXT PRIMARY KEY,url TEXT NOT NULL,key TEXT NOT NULL,text TEXT NOT NULL,vision TEXT NOT NULL);
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
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,target TEXT,created TEXT);
        """)
        for table, column, datatype in (
            ("model_provider", "label", "TEXT NOT NULL DEFAULT ''"),
            ("model_provider", "connections", "TEXT NOT NULL DEFAULT '{}'"),
            ("cases", "tags", "TEXT DEFAULT ''"),
            ("cases", "scenario", "TEXT DEFAULT ''"),
            ("rules", "case_id", "TEXT DEFAULT ''"),
            ("job", "worker_pid", "INTEGER"),
            ("job", "copy_checkpoint", "TEXT"),
            ("job", "visual_review", "TEXT"),
            ("rules", "retrievable", "INTEGER NOT NULL DEFAULT 0"),
            ("event", "category", "TEXT NOT NULL DEFAULT '本地活动'"),
        ):
            if column not in [
                r["name"] for r in c.execute(f"PRAGMA table_info({table})")
            ]:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {datatype}")
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


def tenant_new(c, tenant):
    c.execute(
        "INSERT INTO merchant(id,profile,created)VALUES(?,?,?)", (tenant, "{}", now())
    )
    c.execute(
        "INSERT INTO ledger(tenant,delta,note,created)VALUES(?,?,?,?)",
        (tenant, 120, "开通工作室体验积分", now()),
    )
