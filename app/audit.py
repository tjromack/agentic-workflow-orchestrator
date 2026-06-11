"""Audit: assemble a run's replayable trace from the persisted tables.

Joins the plan, executed steps (with resolved inputs + outputs), guardrail
events, human decisions, and timings into one structure the viewer renders and
``trace.json`` serializes. Reading only — the trace is reconstructed entirely
from what was persisted, which is what makes a completed run replayable.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app import store
from app.executor import Event, StepStatus


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


def _ms(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end:
        return None
    return round((end - start).total_seconds() * 1000)


def _load(value: str | None) -> Any:
    return json.loads(value) if value else None


def list_runs() -> list[dict[str, Any]]:
    return store.list_runs()


def get_trace(run_id: str) -> dict[str, Any] | None:
    run = store.get_run(run_id)
    if not run:
        return None

    plan = store.get_plan_for_run(run_id)
    exec_steps = {s["step_index"]: s for s in store.get_steps(run_id)}
    run_start = _parse(run["created_at"])
    last_end = run_start

    steps: list[dict[str, Any]] = []
    pending_index: int | None = None
    brief: str | None = None

    for ps in (plan["steps"] if plan else []):
        es = exec_steps.get(ps["index"])
        start = _parse(es["created_at"]) if es else None
        end = _parse(es["updated_at"]) if es else None
        if end and (not last_end or end > last_end):
            last_end = end

        status = es["status"] if es else StepStatus.PENDING
        output = _load(es["output_json"]) if es else None
        if status == StepStatus.AWAITING_CHECKPOINT:
            pending_index = ps["index"]
        if ps["tool"] == "write_brief" and status == StepStatus.SUCCEEDED and output:
            brief = output.get("brief_markdown")

        steps.append({
            "index": ps["index"],
            "tool": ps["tool"],
            "description": ps.get("description", ""),
            "expected_output": ps.get("expected_output", ""),
            "consequential": ps.get("consequential", False),
            "status": status,
            "attempts": es["attempts"] if es else 0,
            "plan_inputs": ps.get("inputs"),
            "resolved_inputs": _load(es["inputs_json"]) if es else None,
            "output": output,
            "error": es["error"] if es else None,
            "duration_ms": _ms(start, end),
        })

    events: list[dict[str, Any]] = []
    for e in store.get_events(run_id):
        ev_t = _parse(e["created_at"])
        if ev_t and (not last_end or ev_t > last_end):
            last_end = ev_t
        events.append({
            "kind": e["kind"],
            "step_index": e["step_index"],
            "message": e["message"],
            "data": _load(e["data_json"]),
            "elapsed_ms": _ms(run_start, ev_t),
        })

    decisions = [e for e in events if e["kind"] == Event.HUMAN_DECISION]

    return {
        "run": run,
        "plan": plan,
        "steps": steps,
        "events": events,
        "decisions": decisions,
        "pending_index": pending_index,
        "brief": brief,
        "timings": {
            "started_at": run["created_at"],
            "ended_at": last_end.isoformat() if last_end else None,
            "total_ms": _ms(run_start, last_end),
        },
    }
