"""SQLite persistence. The DB is born in Phase 2 to persist runs + plans;
later phases extend the schema with steps and audit events.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import load_settings
from app.planner import Plan

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    goal        TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(id),
    model_provider  TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    steps_json      TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
"""

_TABLES = ["plans", "runs"]


def _db_path() -> Path:
    path = Path(load_settings().db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def reset_db() -> None:
    """Drop run-state tables and recreate them — clean slate for demos."""
    with connect() as conn:
        for table in _TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    init_db()


def create_run(goal: str, status: str = "planned") -> str:
    run_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            "INSERT INTO runs (id, goal, status, created_at) VALUES (?, ?, ?, ?)",
            (run_id, goal, status, _now()),
        )
    return run_id


def save_plan(run_id: str, plan: Plan) -> str:
    plan_id = uuid.uuid4().hex
    steps_json = json.dumps([s.__dict__ for s in plan.steps])
    with connect() as conn:
        conn.execute(
            """INSERT INTO plans
               (id, run_id, model_provider, model_name, prompt_version,
                steps_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                plan_id, run_id, plan.model_provider, plan.model_name,
                plan.prompt_version, steps_json, plan.created_at,
            ),
        )
    return plan_id


def get_run(run_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def get_plan_for_run(run_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM plans WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    if not row:
        return None
    plan = dict(row)
    plan["steps"] = json.loads(plan.pop("steps_json"))
    return plan


def list_runs() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]
