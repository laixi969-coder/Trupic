"""Persistent conversations, scoped memory and ordered events over existing production jobs."""

import datetime as dt
import hashlib
import os

from flask import abort
from .store import db, dump, ident, now


def enabled(tenant):
    flag = os.getenv("TRUPIC_PERSONAL_AGENT", "1").lower()
    if flag in ("0", "false", "off"):
        return False
    default = "0" if os.getenv("TRUPIC_MODEL_STAGE") == "production" else "100"
    rollout = max(0, min(100, int(os.getenv("TRUPIC_AGENT_ROLLOUT", default))))
    return int(hashlib.sha256(tenant.encode()).hexdigest()[:8], 16) % 100 < rollout


def _ensure_column(c, table, name, definition):
    cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
    if name not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def initialize():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS agent_project(id TEXT PRIMARY KEY, tenant TEXT NOT NULL, title TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS conversation(id TEXT PRIMARY KEY, tenant TEXT NOT NULL, project TEXT,
            title TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS conversation_tenant ON conversation(tenant, archived, created);
        CREATE TABLE IF NOT EXISTS agent_message(seq INTEGER PRIMARY KEY, conversation TEXT NOT NULL,
            role TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL, created TEXT NOT NULL, request_key TEXT,
            UNIQUE(conversation,request_key));
        CREATE INDEX IF NOT EXISTS message_history ON agent_message(conversation,seq);
        CREATE TABLE IF NOT EXISTS agent_task(id TEXT PRIMARY KEY, tenant TEXT NOT NULL, conversation TEXT NOT NULL,
            revision INTEGER NOT NULL, status TEXT NOT NULL, input TEXT NOT NULL, brief TEXT NOT NULL DEFAULT '{}',
            quote TEXT, quote_id TEXT, cost INTEGER, options TEXT NOT NULL DEFAULT '[]', locked TEXT,
            note TEXT NOT NULL DEFAULT '', run TEXT UNIQUE, approval_key TEXT, created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS agent_task_conversation ON agent_task(conversation);
        CREATE TABLE IF NOT EXISTS agent_revision(task TEXT NOT NULL,revision INTEGER NOT NULL,
            status TEXT NOT NULL,input TEXT NOT NULL,brief TEXT NOT NULL,locked TEXT,quote_id TEXT,cost INTEGER,
            PRIMARY KEY(task,revision));
        CREATE TRIGGER IF NOT EXISTS agent_revision_snapshot AFTER UPDATE ON agent_task
        BEGIN
          INSERT INTO agent_revision(task,revision,status,input,brief,locked,quote_id,cost)
          VALUES(NEW.id,NEW.revision,NEW.status,NEW.input,NEW.brief,NEW.locked,NEW.quote_id,NEW.cost)
          ON CONFLICT(task,revision) DO UPDATE SET status=excluded.status,input=excluded.input,
            brief=excluded.brief,locked=excluded.locked,quote_id=excluded.quote_id,cost=excluded.cost;
        END;
        CREATE TABLE IF NOT EXISTS agent_event(seq INTEGER PRIMARY KEY, task TEXT NOT NULL, revision INTEGER NOT NULL,
            type TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS agent_event_cursor ON agent_event(task,seq);
        CREATE TABLE IF NOT EXISTS agent_memory(id TEXT PRIMARY KEY, tenant TEXT NOT NULL, project TEXT NOT NULL,
            name TEXT NOT NULL, value TEXT NOT NULL, kind TEXT NOT NULL, active INTEGER NOT NULL,
            version INTEGER NOT NULL, updated TEXT NOT NULL, UNIQUE(tenant,project,name));
        CREATE TABLE IF NOT EXISTS agent_context_summary(conversation TEXT PRIMARY KEY, tenant TEXT NOT NULL,
            up_to_seq INTEGER NOT NULL, summary TEXT NOT NULL, goals TEXT NOT NULL, decisions TEXT NOT NULL,
            pending TEXT NOT NULL, refs TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS agent_context_summary_tenant ON agent_context_summary(tenant);
        CREATE TABLE IF NOT EXISTS agent_option_lease(task TEXT PRIMARY KEY,revision INTEGER NOT NULL,token TEXT NOT NULL,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_preferences(tenant TEXT PRIMARY KEY, weeks INTEGER NOT NULL, last_sent TEXT);
        CREATE TRIGGER IF NOT EXISTS agent_job_event AFTER UPDATE OF state,stage ON job
        WHEN (OLD.state IS NOT NEW.state OR OLD.stage IS NOT NEW.stage)
          AND json_extract(NEW.spec,'$.plan.agentTask') IS NOT NULL
        BEGIN
          INSERT INTO agent_event(task,revision,type,payload,created)
          SELECT id,revision,'job',json_object('job',NEW.id,'state',NEW.state,'stage',NEW.stage,'error',NEW.error),
                 strftime('%Y-%m-%dT%H:%M:%fZ','now')
          FROM agent_task WHERE id=json_extract(NEW.spec,'$.plan.agentTask') AND tenant=NEW.tenant;
        END;
        """)
        _ensure_column(c, "agent_memory", "status", "TEXT NOT NULL DEFAULT 'confirmed'")
        _ensure_column(c, "agent_memory", "source_message_id", "INTEGER")
        _ensure_column(c, "agent_memory", "expires_at", "TEXT")
        _ensure_column(c, "agent_memory", "hit_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(c, "agent_memory", "last_used", "TEXT")


def message(c, conversation, role, kind, content, key=None):
    c.execute(
        "INSERT INTO agent_message(conversation,role,kind,content,created,request_key) VALUES(?,?,?,?,?,?)",
        (conversation, role, kind, dump(content), now(), key),
    )


def event(c, task, kind, payload):
    c.execute(
        "INSERT INTO agent_event(task,revision,type,payload,created) VALUES(?,?,?,?,?)",
        (task["id"], task["revision"], kind, dump(payload), now()),
    )


def check_revision(task, expected):
    if type(expected) is not int or task["revision"] != expected:
        abort(409, description="任务已更新，请查看当前版本。")


def new_conversation(c, tenant, project=None):
    cid = ident()
    c.execute(
        "INSERT INTO conversation(id,tenant,project,title,created) VALUES(?,?,?,?,?)",
        (cid, tenant, project, "新对话", now()),
    )
    return cid


def memory_rows(c, tenant, project, include_candidates=True):
    today = dt.date.today().isoformat()
    rows = []
    for r in c.execute(
        """SELECT id,project,name,value,kind,active,version,updated,
                  COALESCE(status,'confirmed') AS status,source_message_id,expires_at,
                  COALESCE(hit_count,0) AS hit_count,last_used
           FROM agent_memory WHERE tenant=? AND project IN ('',?) ORDER BY rowid""",
        (tenant, project or ""),
    ):
        item = dict(r)
        if item["expires_at"] and item["expires_at"] < today and item["status"] == "confirmed":
            item["status"] = "expired"
            item["active"] = 0
        if not include_candidates and item["status"] != "confirmed":
            continue
        rows.append(item)
    return rows


def invalidate_summaries(c, tenant, project=None):
    """Purge cached conversation summaries when memory changes or is deleted (PRD §23)."""
    if project:
        c.execute(
            """DELETE FROM agent_context_summary WHERE tenant=? AND conversation IN
               (SELECT id FROM conversation WHERE tenant=? AND project=?)""",
            (tenant, tenant, project),
        )
    else:
        c.execute("DELETE FROM agent_context_summary WHERE tenant=?", (tenant,))


def project_for(c, tenant, pid):
    if (
        pid
        and not c.execute(
            "SELECT 1 FROM agent_project WHERE tenant=? AND id=?", (tenant, pid)
        ).fetchone()
    ):
        abort(404, description="找不到这个项目。")
    return pid or None


def run_status(c, task):
    if not task["run"] or task["status"] == "cancelled":
        return task["status"]
    jobs = c.execute(
        """SELECT j.state,j.stage FROM creative_run r,json_each(r.items) i JOIN job j
        ON j.id=json_extract(i.value,'$.job') WHERE r.id=? AND r.tenant=?""",
        (task["run"], task["tenant"]),
    ).fetchall()
    states = {j["state"] for j in jobs}
    if "running" in states:
        return (
            "reviewing"
            if all(
                "审核" in (j["stage"] or "") for j in jobs if j["state"] == "running"
            )
            else "running"
        )
    if "queued" in states:
        return "queued"
    return "delivered" if states == {"complete"} else "failed"


def metrics(c):
    counts = dict(
        c.execute("""
        WITH task_states AS (
          SELECT t.id,CASE
            WHEN t.run IS NULL OR t.status='cancelled' THEN t.status
            WHEN SUM(j.state='running')>0 THEN
              CASE WHEN SUM(j.state='running' AND COALESCE(j.stage,'') NOT LIKE '%审核%')>0 THEN 'running' ELSE 'reviewing' END
            WHEN SUM(j.state='queued')>0 THEN 'queued'
            WHEN COUNT(j.id)>0 AND SUM(j.state='complete')=COUNT(j.id) THEN 'delivered'
            ELSE 'failed' END AS state
          FROM agent_task t LEFT JOIN creative_run r ON r.id=t.run
          LEFT JOIN json_each(r.items) i ON TRUE LEFT JOIN job j ON j.id=json_extract(i.value,'$.job')
          GROUP BY t.id)
        SELECT state,COUNT(*) FROM task_states GROUP BY state""")
    )
    mem = dict(
        c.execute(
            "SELECT COALESCE(status,'confirmed'), COUNT(*) FROM agent_memory GROUP BY COALESCE(status,'confirmed')"
        )
    )
    compacted = c.execute("SELECT COUNT(*) FROM agent_context_summary").fetchone()[0]
    return dict(
        conversations=c.execute(
            "SELECT COUNT(*) FROM conversation WHERE archived=0"
        ).fetchone()[0],
        tasks=sum(counts.values()),
        states=counts,
        memories=dict(confirmed=mem.get("confirmed", 0), candidate=mem.get("candidate", 0)),
        compactedConversations=compacted,
    )


def preferences(c, tenant):
    row = c.execute(
        "SELECT weeks,last_sent FROM agent_preferences WHERE tenant=?", (tenant,)
    ).fetchone()
    return dict(row) if row else dict(weeks=1, last_sent=None)
