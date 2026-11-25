"""MemoraX-inspired 4-layer context & memory manager for Trupic V4 Personal Agent.

Implements PRD §23 + MemoraX Code principles:
1. Four clear memory boundaries:
   - Merchant long-term memory (facts, preferences, shared assets across chats)
   - Project memory (campaign-scoped facts & assets, isolated to one project)
   - Task memory (authoritative snapshot read directly from agent_task, never guessed)
   - Ephemeral conversation context (verified compaction summary + bounded recent turns)
2. Selective retrieval: bring back relevant confirmed memories instead of blindly dumping all.
3. Intent-based writeback & forget:
   - Explicit remember/forget commands act cleanly with semantic deduplication
   - Implicit durable store facts/preferences create 'candidate' entries (1-tap confirm)
   - Temporary promotional/event prices are NEVER auto-written as permanent store memory
4. Verified compaction: compacts long conversations into goals/decisions/pending/refs while
   preserving raw messages and invalidating summaries whenever memory is corrected/deleted.
"""

import datetime as dt
import json
import re

from .agent_store import invalidate_summaries, memory_rows
from .store import dump, ident, now

# Compaction thresholds (character/turn budget)
COMPACT_MIN_MESSAGES = 12
COMPACT_MIN_CHARS = 1600
RECENT_WINDOW = 6
MAX_SELECTIVE_MEMORIES = 8

# Explicit memory commands
EXPLICIT_REMEMBER = re.compile(
    r"^(?:请|帮我|给我)?(?:记住|记一下|记下来|长期记住|保存记忆)[：:\s，,]*(.+)$",
    re.S,
)
EXPLICIT_FORGET = re.compile(
    r"^(?:请|帮我|给我)?(?:忘掉|忘记|不要记|别记|删除记忆|忘了吧)[：:\s，,]*(.+)$",
    re.S,
)

# Guard: temporary/promotional price signals must NEVER become permanent store facts
PROMO_PRICE_GUARD = re.compile(
    r"(?:今天|今日|明天|本周|这周|周末|限时|特价|活动价|秒杀|立减|满减|打折|促销|原价|现价|仅需|只要|\d+(?:\.\d+)?\s*(?:元|块|折))"
)

# Implicit durable signals: (regex, default_name, kind)
DURABLE_PATTERNS = (
    (
        re.compile(r"(?:我们店|本店|门店|店铺)?(?:地址|位置)(?:在|是)[：:\s]*([^，。！？\n]{3,40})"),
        "门店地址",
        "fact",
    ),
    (
        re.compile(r"(?:我们店|本店|店里)在([^，。！？\n]{3,36}(?:路|街|广场|商场|楼|号|店|旁|对面|附近|区|县|镇))"),
        "门店地址",
        "fact",
    ),
    (
        re.compile(r"(?:营业时间|出炉时间|开门时间)(?:是|为)?[：:\s]*([^，。！？\n]{3,40})"),
        "营业时间",
        "fact",
    ),
    (
        re.compile(r"(?:我们|店里|本店)?(?:招牌|主打)(?:菜|品|产品|饮品|服务)?(?:是|有)[：:\s]*([^，。！？\n]{2,36})"),
        "门店招牌",
        "fact",
    ),
    (
        re.compile(r"(?:以后|平时|每次)(?:文案|海报|视频|宣传|排版)?(?:都|尽量|不要|别)([^，。！？\n]{3,40})"),
        "创作偏好",
        "preference",
    ),
)

KEY_VALUE_SPLIT = re.compile(r"^([^：:，,=\s]{1,20})[：:=为是]\s*(.+)$")


def _tokens(text):
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text.lower()).strip()
    out = set()
    for part in cleaned.split():
        if len(part) >= 2:
            out.add(part)
        cjk = "".join(ch for ch in part if "\u4e00" <= ch <= "\u9fff")
        for i in range(max(0, len(cjk) - 1)):
            out.add(cjk[i : i + 2])
    return out


def _normalize(text):
    return re.sub(r"[\s，。！？、：:,.!?]+", "", (text or "").strip().lower())


def select_memories(c, tenant, project, query_text="", limit=MAX_SELECTIVE_MEMORIES):
    """Select relevant confirmed, active, non-expired memories with project precedence."""
    rows = [
        r
        for r in memory_rows(c, tenant, project, include_candidates=False)
        if r["active"] and r["status"] == "confirmed"
    ]
    # Project entries override same-named global merchant entries
    scoped = {}
    for r in sorted(rows, key=lambda item: bool(item["project"])):
        scoped[r["name"]] = r
    candidates = list(scoped.values())
    if len(candidates) <= limit:
        selected = candidates
    else:
        q_tokens = _tokens(query_text)

        def score(item):
            s = 0.0
            if item["project"]:
                s += 3.0  # Current project memory has highest contextual salience
            if item["kind"] == "preference":
                s += 1.5  # User profile preferences stay sticky across turns
            elif item["kind"] == "asset":
                s += 1.0
            if q_tokens:
                m_tokens = _tokens(f"{item['name']} {item['value']}")
                overlap = len(q_tokens & m_tokens)
                s += overlap * 2.5
                if item["name"] in (query_text or ""):
                    s += 4.0
            s += min(item.get("hit_count", 0) * 0.1, 1.0)
            return s

        selected = sorted(candidates, key=score, reverse=True)[:limit]

    recalled = [
        dict(
            id=r["id"],
            name=r["name"],
            value=r["value"],
            kind=r["kind"],
            scope="project" if r["project"] else "merchant",
        )
        for r in selected
    ]
    return selected, recalled


def touch_memories(c, memory_ids):
    if not memory_ids:
        return
    ts = now()
    for mid in memory_ids:
        c.execute(
            "UPDATE agent_memory SET hit_count=COALESCE(hit_count,0)+1, last_used=? WHERE id=?",
            (ts, mid),
        )


def _infer_remember_entry(raw_body):
    body = raw_body.strip().rstrip("。！! ")
    if not body or len(body) > 240:
        return None
    if m := KEY_VALUE_SPLIT.match(body):
        name, value = m[1].strip()[:60], m[2].strip()[:240]
        kind = "preference" if re.search(r"风格|语气|偏好|不要|别用|喜欢|字要", body) else "fact"
        return name, value, kind
    for pattern, default_name, default_kind in DURABLE_PATTERNS:
        if m := pattern.search(body):
            return default_name, body[:240], default_kind
    kind = "preference" if re.search(r"以后|不要|别用|喜欢|风格|语气|字要|简约|实在", body) else "fact"
    name = "创作偏好" if kind == "preference" else "门店备注"
    return name, body[:240], kind


def handle_memory_command(c, tenant, project, text, source_seq=None):
    """Handle explicit '记住…' / '忘掉…' commands cleanly without starting paid tasks.

    Returns reply text if handled as a memory command, or None otherwise.
    """
    stripped = text.strip()
    if m := EXPLICIT_FORGET.match(stripped):
        target = m[1].strip().rstrip("。！! ")
        if not target:
            return "请告诉我希望忘掉哪条记忆的名称或关键词。"
        rows = memory_rows(c, tenant, project, include_candidates=True)
        norm_target = _normalize(target)
        matched = [
            r
            for r in rows
            if norm_target in _normalize(r["name"])
            or _normalize(r["name"]) in norm_target
            or norm_target in _normalize(r["value"])
        ]
        # Prefer exact/scoped match; delete only the most specific single target (MemoraX principle)
        if not matched:
            return f"当前记忆里没有找到关于「{target[:24]}」的条目，其他记忆保持不变。"
        matched.sort(
            key=lambda r: (
                _normalize(r["name"]) == norm_target,
                bool(r["project"]),
                r["status"] == "confirmed",
            ),
            reverse=True,
        )
        victim = matched[0]
        c.execute("DELETE FROM agent_memory WHERE id=? AND tenant=?", (victim["id"], tenant))
        invalidate_summaries(c, tenant, victim["project"] or None)
        return f"已忘掉记忆「{victim['name']}」（{victim['value']}），不影响其他店铺资料。"

    if m := EXPLICIT_REMEMBER.match(stripped):
        parsed = _infer_remember_entry(m[1])
        if not parsed:
            return "请再说具体一点，我好帮你准确记下来。"
        name, value, kind = parsed
        scope_project = project or ""
        if not scope_project and kind == "fact" and PROMO_PRICE_GUARD.search(value):
            return (
                f"「{value}」看起来像单次活动或临时价格，为避免以后做海报用错旧价格，"
                "我没有把它写入永久店铺记忆。如需在当前活动复用，请先关联项目或直接在「助理记忆」里设有效期。"
            )
        existing = c.execute(
            "SELECT * FROM agent_memory WHERE tenant=? AND project=? AND name=?",
            (tenant, scope_project, name),
        ).fetchone()
        if existing:
            if _normalize(existing["value"]) == _normalize(value) and existing["active"] and (existing["status"] or "confirmed") == "confirmed":
                return f"这条记忆已经在册了：「{name} · {existing['value']}」。"
            c.execute(
                """UPDATE agent_memory SET value=?,kind=?,active=1,status='confirmed',
                   source_message_id=COALESCE(?,source_message_id),version=version+1,updated=?
                   WHERE id=?""",
                (value, kind, source_seq, now(), existing["id"]),
            )
            invalidate_summaries(c, tenant, scope_project or None)
            return f"已更新记忆「{name}」为：{value}。以后创作会自动参考。"
        mid = ident()
        c.execute(
            """INSERT INTO agent_memory(id,tenant,project,name,value,kind,active,version,updated,status,source_message_id)
               VALUES(?,?,?,?,?,?,1,1,?,'confirmed',?)""",
            (mid, tenant, scope_project, name, value, kind, now(), source_seq),
        )
        invalidate_summaries(c, tenant, scope_project or None)
        scope_label = "当前项目" if scope_project else "店铺长期"
        return f"已记入{scope_label}记忆：「{name} · {value}」。随时可以在右上角「记忆」里修改或删除。"

    return None


def propose_candidates(c, tenant, project, text, source_seq=None):
    """Detect durable store facts or preferences from normal conversation and record as candidates.

    Strictly follows PRD §23 & MemoraX Code:
    - Never auto-saves promotional/activity prices into permanent store facts
    - Semantic dedupe: skips if identical or already tracked
    - Stored as status='candidate', active=0 until merchant confirms with 1 tap
    """
    if not text or len(text.strip()) < 6:
        return []
    existing = memory_rows(c, tenant, project, include_candidates=True)
    by_name = {(r["project"], r["name"]): r for r in existing}
    norm_values = {_normalize(r["value"]) for r in existing}
    created = []
    scope_project = ""  # Durable store profile/preferences default to merchant scope

    for pattern, name, kind in DURABLE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        raw = match.group(0).strip().rstrip("，,。.!！ ")
        extracted = match.group(1).strip().rstrip("，,。.!！ ")
        val = extracted if kind == "fact" and len(extracted) >= 3 else raw
        if not val or len(val) > 120:
            continue
        # Guard: temporary prices / promos never become permanent store facts
        if kind == "fact" and PROMO_PRICE_GUARD.search(raw):
            continue
        if _normalize(val) in norm_values:
            continue
        if (scope_project, name) in by_name:
            continue
        mid = ident()
        c.execute(
            """INSERT INTO agent_memory(id,tenant,project,name,value,kind,active,version,updated,status,source_message_id)
               VALUES(?,?,?,?,?,?,0,1,?,'candidate',?)""",
            (mid, tenant, scope_project, name, val, kind, now(), source_seq),
        )
        created.append(dict(id=mid, name=name, value=val, kind=kind, version=1))
        norm_values.add(_normalize(val))
        by_name[(scope_project, name)] = dict(id=mid, name=name, value=val)
    return created


def compact_conversation(c, tenant, cid, up_to_seq=None):
    """Build or refresh a verified compaction summary when history exceeds budget (PRD §23).

    Authoritative task decisions are always read directly from agent_task, never guessed.
    Raw messages remain untouched in agent_message.
    """
    params = [cid]
    clause = ""
    if up_to_seq is not None:
        clause = " AND seq < ?"
        params.append(up_to_seq)
    rows = c.execute(
        f"SELECT seq,role,kind,content FROM agent_message WHERE conversation=?{clause} ORDER BY seq",
        params,
    ).fetchall()
    text_rows = [r for r in rows if r["kind"] == "text"]
    total_chars = sum(len(json.loads(r["content"]).get("text", "")) for r in text_rows)
    if len(text_rows) <= COMPACT_MIN_MESSAGES and total_chars <= COMPACT_MIN_CHARS:
        return None

    older = text_rows[:-RECENT_WINDOW] if len(text_rows) > RECENT_WINDOW else text_rows
    if not older:
        return None
    cutoff_seq = older[-1]["seq"]

    existing = c.execute(
        "SELECT * FROM agent_context_summary WHERE conversation=? AND tenant=?",
        (cid, tenant),
    ).fetchone()
    if existing and existing["up_to_seq"] >= cutoff_seq:
        return dict(
            upToSeq=existing["up_to_seq"],
            summary=existing["summary"],
            goals=json.loads(existing["goals"]),
            decisions=json.loads(existing["decisions"]),
            pending=json.loads(existing["pending"]),
            refs=json.loads(existing["refs"]),
            updated=existing["updated"],
        )

    # Extract distinct user goals from older turns (deduped, ignoring trivial greetings)
    greetings = {"你好", "您好", "在吗", "好的", "谢谢", "嗯", "ok"}
    goals = []
    seen_goals = set()
    refs = []
    for r in older:
        payload = json.loads(r["content"])
        if r["role"] == "user":
            txt = payload.get("text", "").strip()
            norm = _normalize(txt)
            if txt and norm not in greetings and norm not in seen_goals:
                seen_goals.add(norm)
                goals.append(txt[:80])
            if payload.get("asset") and payload["asset"] not in refs:
                refs.append("asset:" + payload["asset"])

    # Read authoritative decisions & pending items directly from agent_task (DB truth)
    decisions = []
    pending = []
    for t in c.execute(
        "SELECT id,status,input,locked,cost,quote_id FROM agent_task WHERE conversation=? AND tenant=? ORDER BY rowid",
        (cid, tenant),
    ):
        inp = json.loads(t["input"])
        locked = json.loads(t["locked"]) if t["locked"] else None
        if inp.get("workRef"):
            wref = f"work:{inp['workRef']['id']}@v{inp['workRef']['version']}"
            if wref not in refs:
                refs.append(wref)
        if locked:
            title = locked.get("title") or locked.get("body", "")[:30]
            decisions.append(f"{inp.get('kind','poster')}({inp.get('ratio','')})定稿：{title}")
        if t["status"] in ("waiting_input", "waiting_copy", "waiting_script", "quoted"):
            pending.append(f"任务 {t['id'][:6]}：{t['status']}（{inp.get('brief','')[:36]}）")

    parts = []
    if goals:
        parts.append("历史目标：" + "；".join(goals[-4:]))
    if decisions:
        parts.append("已确认决定：" + "；".join(decisions[-3:]))
    if pending:
        parts.append("待办事项：" + "；".join(pending[-3:]))
    summary_text = "\n".join(parts)[:500] or f"已完成 {len(older)} 轮前期沟通。"

    ts = now()
    c.execute(
        """INSERT INTO agent_context_summary(conversation,tenant,up_to_seq,summary,goals,decisions,pending,refs,updated)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(conversation) DO UPDATE SET up_to_seq=excluded.up_to_seq,summary=excluded.summary,
             goals=excluded.goals,decisions=excluded.decisions,pending=excluded.pending,
             refs=excluded.refs,updated=excluded.updated""",
        (
            cid,
            tenant,
            cutoff_seq,
            summary_text,
            dump(goals[-6:]),
            dump(decisions[-6:]),
            dump(pending[-6:]),
            dump(refs[-8:]),
            ts,
        ),
    )
    return dict(
        upToSeq=cutoff_seq,
        summary=summary_text,
        goals=goals[-6:],
        decisions=decisions[-6:],
        pending=pending[-6:],
        refs=refs[-8:],
        updated=ts,
    )


def build_context_packet(c, tenant, conv, question="", up_to_seq=None, write_summary=False):
    """Assemble the 4-layer bounded context packet for dialogue or inspection."""
    profile = json.loads(
        c.execute("SELECT profile FROM merchant WHERE id=?", (tenant,)).fetchone()[0]
    )
    selected, recalled = select_memories(c, tenant, conv["project"], question)
    merchant_mem = [f"{r['name']}：{r['value']}" for r in selected if not r["project"] and r["kind"] != "asset"]
    project_mem = [f"{r['name']}：{r['value']}" for r in selected if r["project"] and r["kind"] != "asset"]

    task = c.execute(
        "SELECT id,revision,input,locked,brief,status,cost,quote_id FROM agent_task WHERE conversation=? AND tenant=? ORDER BY rowid DESC LIMIT 1",
        (conv["id"], tenant),
    ).fetchone()
    task_snapshot = None
    if task:
        inp = json.loads(task["input"])
        task_snapshot = dict(
            id=task["id"],
            revision=task["revision"],
            status=task["status"],
            kind=inp.get("kind"),
            ratio=inp.get("ratio"),
            brief=inp.get("brief", "")[:200],
            cost=task["cost"],
            locked=json.loads(task["locked"]) if task["locked"] else None,
        )

    compacted = None
    if write_summary:
        compacted = compact_conversation(c, tenant, conv["id"], up_to_seq)
    else:
        row = c.execute(
            "SELECT * FROM agent_context_summary WHERE conversation=? AND tenant=?",
            (conv["id"], tenant),
        ).fetchone()
        if row:
            compacted = dict(
                upToSeq=row["up_to_seq"],
                summary=row["summary"],
                goals=json.loads(row["goals"]),
                decisions=json.loads(row["decisions"]),
                pending=json.loads(row["pending"]),
                refs=json.loads(row["refs"]),
                updated=row["updated"],
            )

    params = [conv["id"]]
    clause = ""
    if up_to_seq is not None:
        clause = " AND seq < ?"
        params.append(up_to_seq)
    recent_rows = c.execute(
        f"""SELECT role,content FROM agent_message WHERE conversation=?{clause}
            AND kind='text' ORDER BY seq DESC LIMIT ?""",
        params + [RECENT_WINDOW],
    ).fetchall()
    recent = [
        dict(role=r["role"], text=json.loads(r["content"]).get("text", "")[:240])
        for r in reversed(recent_rows)
    ]

    return dict(
        layers=dict(
            merchant=dict(profile=profile, memories=merchant_mem),
            project=dict(id=conv["project"], memories=project_mem),
            task=task_snapshot,
            ephemeral=dict(compacted=compacted, recent=recent),
        ),
        recalled=recalled,
    )
