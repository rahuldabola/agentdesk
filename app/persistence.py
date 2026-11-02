"""Durable run state: the LangGraph checkpointer plus a small index of runs.

Two stores, one SQLite file:

* The **checkpointer** (LangGraph's SqliteSaver) snapshots the full graph state
  after every node, keyed by `thread_id` = the run id. That is what makes a run
  resumable: after a crash, a deploy, or a human-in-the-loop pause, the graph
  continues from the last finished node instead of starting over.
* The **run index** is a plain table with one row per run (question, status,
  timestamps, outcome). Listing runs from checkpoints would mean deserialising
  every thread's state; the index answers "what runs exist" in one query.

`AGENTDESK_RUNS_DB=memory` keeps both in-process (tests, throwaway demos).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from app.config import get_settings

RUN_STATUSES = ("running", "awaiting_review", "completed", "failed", "cancelled")

# Columns a run's lifecycle may update (identity and timestamps are set elsewhere).
_UPDATABLE = {
    "review_plan",
    "status",
    "outcome",
    "error",
    "citations",
    "revisions",
    "llm_calls",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "elapsed_ms",
    "usage_by_agent",
}

# Added after the first release; created on open so an existing runs DB upgrades
# in place instead of failing on the new columns.
_MIGRATIONS = {
    "llm_calls": "INTEGER",
    "tokens_in": "INTEGER",
    "tokens_out": "INTEGER",
    "cost_usd": "REAL",
    "elapsed_ms": "REAL",
    "usage_by_agent": "TEXT",  # JSON: per-agent usage, see observability.summarize_trace
}


def _is_memory(path: str) -> bool:
    return path.strip().lower() in ("memory", ":memory:", "")


def _connect(path: str) -> sqlite3.Connection:
    if _is_memory(path):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        # WAL lets the checkpointer write while the run index is read.
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


class RunStore:
    """Thread-safe index of runs. Every method takes the one lock it needs."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id      TEXT PRIMARY KEY,
                    question    TEXT NOT NULL,
                    depth       TEXT,
                    review_plan INTEGER NOT NULL DEFAULT 0,
                    status      TEXT NOT NULL,
                    outcome     TEXT,
                    error       TEXT,
                    citations   INTEGER,
                    revisions   INTEGER,
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS runs_created ON runs(created_at)")
            existing = {r["name"] for r in self._conn.execute("PRAGMA table_info(runs)")}
            for column, sql_type in _MIGRATIONS.items():
                if column not in existing:
                    self._conn.execute(f"ALTER TABLE runs ADD COLUMN {column} {sql_type}")
            self._conn.commit()

    def create(self, run_id: str, question: str, depth: str, review_plan: bool) -> dict:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs (run_id, question, depth, review_plan, status, created_at,"
                " updated_at) VALUES (?, ?, ?, ?, 'running', ?, ?)",
                (run_id, question, depth, int(review_plan), now, now),
            )
            self._conn.commit()
        return self.get(run_id)  # type: ignore[return-value]

    def update(self, run_id: str, **fields) -> None:
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError(f"unknown run fields: {sorted(unknown)}")
        if "status" in fields and fields["status"] not in RUN_STATUSES:
            raise ValueError(f"unknown run status: {fields['status']}")
        if isinstance(fields.get("usage_by_agent"), dict):
            fields["usage_by_agent"] = json.dumps(fields["usage_by_agent"])
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE runs SET {assignments}, updated_at = ? WHERE run_id = ?",
                (*fields.values(), time.time(), run_id),
            )
            self._conn.commit()

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return _row(row) if row else None

    def list(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row(r) for r in rows]

    def delete(self, run_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            self._conn.commit()
        return cur.rowcount > 0


def _row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["review_plan"] = bool(data["review_plan"])
    raw = data.get("usage_by_agent")
    data["usage_by_agent"] = json.loads(raw) if raw else {}
    return data


_lock = threading.Lock()
_checkpointer: BaseCheckpointSaver | None = None
_run_store: RunStore | None = None


def _build() -> tuple[BaseCheckpointSaver, RunStore]:
    path = get_settings().runs_db
    if _is_memory(path):
        return InMemorySaver(), RunStore(_connect(path))

    from langgraph.checkpoint.sqlite import SqliteSaver

    return SqliteSaver(_connect(path)), RunStore(_connect(path))


def _ensure() -> None:
    global _checkpointer, _run_store
    with _lock:
        if _checkpointer is None or _run_store is None:
            _checkpointer, _run_store = _build()


def get_checkpointer() -> BaseCheckpointSaver:
    _ensure()
    return _checkpointer  # type: ignore[return-value]


def get_run_store() -> RunStore:
    _ensure()
    return _run_store  # type: ignore[return-value]


def reset_persistence() -> None:
    """Forget the cached stores so the next call re-reads AGENTDESK_RUNS_DB (tests)."""
    global _checkpointer, _run_store
    with _lock:
        _checkpointer = None
        _run_store = None


def runs_db_path() -> str:
    path = get_settings().runs_db
    return "memory" if _is_memory(path) else os.path.abspath(path)
