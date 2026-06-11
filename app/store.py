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

CREATE TABLE IF NOT EXISTS steps (
    id          TEXT PRIMARY KEY,        -- "{run_id}:{step_index}"
    run_id      TEXT NOT NULL REFERENCES runs(id),
    step_index  INTEGER NOT NULL,
    tool        TEXT NOT NULL,
    status      TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    inputs_json TEXT,
    output_json TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- The replayable-trace backbone: guardrail events, step lifecycle, and (later)
-- human decisions. The Phase 5 audit viewer renders this table.
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES runs(id),
    step_index  INTEGER,
    kind        TEXT NOT NULL,
    message     TEXT NOT NULL,
    data_json   TEXT,
    created_at  TEXT NOT NULL
);
"""

_TABLES = ["events", "steps", "plans", "runs"]


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


def set_run_status(run_id: str, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))


def record_step(
    run_id: str, step_index: int, tool: str, status: str, *,
    attempts: int = 0, inputs: Any = None, output: Any = None, error: str | None = None,
) -> None:
    """Upsert a step's current state, keyed on (run_id, step_index)."""
    now = _now()
    with connect() as conn:
        conn.execute(
            """INSERT INTO steps
               (id, run_id, step_index, tool, status, attempts, inputs_json,
                output_json, error, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 status=excluded.status, attempts=excluded.attempts,
                 output_json=excluded.output_json, error=excluded.error,
                 updated_at=excluded.updated_at""",
            (
                f"{run_id}:{step_index}", run_id, step_index, tool, status, attempts,
                json.dumps(inputs) if inputs is not None else None,
                json.dumps(output) if output is not None else None,
                error, now, now,
            ),
        )


def record_event(
    run_id: str, kind: str, message: str, *,
    step_index: int | None = None, data: Any = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO events
               (id, run_id, step_index, kind, message, data_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                uuid.uuid4().hex, run_id, step_index, kind, message,
                json.dumps(data) if data is not None else None, _now(),
            ),
        )


def get_steps(run_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM steps WHERE run_id = ? ORDER BY step_index", (run_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_events(run_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE run_id = ? ORDER BY created_at, id", (run_id,)
        ).fetchall()
    return [dict(r) for r in rows]
