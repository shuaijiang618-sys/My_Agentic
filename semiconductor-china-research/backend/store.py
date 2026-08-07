"""持久层:SQLite(backend/data/runs.db) · Block 5。

一张表 runs,每一轮研究存一行。它同时撑起三件事:
  1. 历史对话:list_conversations / get_conversation / delete_conversation
  2. 动画复现:events 字段存整轮事件流,点历史可原样回放
  3. 多轮记忆:load_history 取前几轮「问题+结论摘要」,重建追问上下文
"""
import json
import time
import uuid
import sqlite3

from .config import RUNS_DB

# 多轮记忆:最多带入最近 N 轮;每轮结论摘要截断字数(防 token 膨胀)
MEMORY_TURN_LIMIT = 5
BRIEF_SUMMARY_CHARS = 400


def _db():
    c = sqlite3.connect(RUNS_DB)
    c.execute("""
        CREATE TABLE IF NOT EXISTS runs(
            id TEXT PRIMARY KEY,
            ts REAL NOT NULL,
            session TEXT NOT NULL,
            query TEXT NOT NULL,
            events TEXT NOT NULL,
            brief TEXT
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_runs_session_ts ON runs(session, ts)")
    _migrate_runs(c)
    return c


def _migrate_runs(c: sqlite3.Connection) -> None:
    """Phase 3 M3.3 · 扩展 runs 表(幂等 ALTER)。"""
    cols = {r[1] for r in c.execute("PRAGMA table_info(runs)").fetchall()}
    if "request_id" not in cols:
        c.execute("ALTER TABLE runs ADD COLUMN request_id TEXT")
    if "duration_ms" not in cols:
        c.execute("ALTER TABLE runs ADD COLUMN duration_ms INTEGER")
    c.commit()


_db().close()


def brief_summary(brief: str, limit: int = BRIEF_SUMMARY_CHARS) -> str:
    """截断简报用于多轮记忆前缀。"""
    if not brief:
        return ""
    text = brief.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def load_history(session: str, limit: int = MEMORY_TURN_LIMIT):
    """取该会话 (query, brief) 历史,用于重建多轮记忆上下文。"""
    try:
        c = _db()
        rows = c.execute(
            "SELECT query, brief FROM runs WHERE session=? ORDER BY ts ASC",
            (session,),
        ).fetchall()
        c.close()
        if limit and len(rows) > limit:
            rows = rows[-limit:]
        return rows
    except Exception:
        return []


def save_run(
    session: str,
    query: str,
    events: list,
    brief: str,
    *,
    request_id: str | None = None,
    duration_ms: int | None = None,
) -> str | None:
    """一轮跑完落库;返回 run id。"""
    rid = uuid.uuid4().hex[:12]
    try:
        c = _db()
        c.execute(
            "INSERT INTO runs(id, ts, session, query, events, brief, request_id, duration_ms) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                rid, time.time(), session, query,
                json.dumps(events, ensure_ascii=False), brief,
                request_id, duration_ms,
            ),
        )
        c.commit()
        c.close()
        return rid
    except Exception:
        return None


def db_stats() -> dict:
    """runs.db 汇总统计。"""
    try:
        c = _db()
        total = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        sessions = c.execute("SELECT COUNT(DISTINCT session) FROM runs").fetchone()[0]
        avg_dur = c.execute(
            "SELECT AVG(duration_ms) FROM runs WHERE duration_ms IS NOT NULL"
        ).fetchone()[0]
        c.close()
        return {
            "total_runs": total,
            "sessions": sessions,
            "avg_duration_ms": int(avg_dur) if avg_dur else None,
        }
    except Exception:
        return {"total_runs": 0, "sessions": 0, "avg_duration_ms": None}


def list_conversations():
    """按 session 归并会话列表,最近活跃在前。"""
    c = _db()
    rows = c.execute("SELECT session, query, ts FROM runs ORDER BY ts ASC").fetchall()
    c.close()
    conv = {}
    for session, query, ts in rows:
        conv.setdefault(session, {"session": session, "title": query, "n_turns": 0, "last_ts": ts})
        conv[session]["n_turns"] += 1
        conv[session]["last_ts"] = ts
    return sorted(conv.values(), key=lambda x: x["last_ts"], reverse=True)


def get_conversation(session: str):
    """某会话全部轮次(含事件流,供前端复现动画)。"""
    c = _db()
    rows = c.execute(
        "SELECT id, ts, query, events, brief FROM runs WHERE session=? ORDER BY ts ASC",
        (session,),
    ).fetchall()
    c.close()
    out = []
    for r in rows:
        try:
            events = json.loads(r[3])
        except (json.JSONDecodeError, TypeError):
            events = []
        out.append({"id": r[0], "ts": r[1], "query": r[2], "events": events, "brief": r[4]})
    return out


def delete_conversation(session: str) -> int:
    c = _db()
    n = c.execute("DELETE FROM runs WHERE session=?", (session,)).rowcount
    c.commit()
    c.close()
    return n


def session_stats(session: str) -> dict:
    """会话统计(轮数、首轮问题)。"""
    c = _db()
    row = c.execute(
        "SELECT COUNT(*), MIN(query), MAX(ts) FROM runs WHERE session=?",
        (session,),
    ).fetchone()
    c.close()
    return {"session": session, "n_turns": row[0] or 0, "title": row[1] or "", "last_ts": row[2]}
