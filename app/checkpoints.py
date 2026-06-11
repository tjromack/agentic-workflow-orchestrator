"""Human checkpoints: pause, record the decision, resume or halt.

A run that paused at a consequential step (Phase 3) is reconstructed here from
its persisted plan + step outputs. The human decision is recorded as an event in
the audit trace, then the executor resumes — carrying completed steps forward and
running only the approved step onward — or halts on rejection.
"""

from __future__ import annotations

import json

from app import store
from app.executor import Event, Executor, RunResult
from app.planner import Plan, PlanStep
from app.registry import ToolRegistry

VALID_DECISIONS = {"approve", "reject"}


class CheckpointError(Exception):
    """Raised when a run cannot be resumed (missing, or no pending checkpoint)."""


def load_plan(run_id: str) -> Plan:
    run = store.get_run(run_id)
    plan_row = store.get_plan_for_run(run_id)
    if not run or not plan_row:
        raise CheckpointError(f"No persisted plan for run {run_id}.")
    steps = [PlanStep(**s) for s in plan_row["steps"]]
    return Plan(
        goal=run["goal"],
        steps=steps,
        model_provider=plan_row["model_provider"],
        model_name=plan_row["model_name"],
        prompt_version=plan_row["prompt_version"],
        created_at=plan_row["created_at"],
    )


def prior_outputs(run_id: str) -> dict[int, dict]:
    """Outputs of steps that already succeeded — the resume context."""
    out: dict[int, dict] = {}
    for s in store.get_steps(run_id):
        if s["status"] == "succeeded" and s["output_json"]:
            out[s["step_index"]] = json.loads(s["output_json"])
    return out


def pending_checkpoint(run_id: str) -> int | None:
    """The step index currently awaiting human approval, if any."""
    for s in store.get_steps(run_id):
        if s["status"] == "awaiting_checkpoint":
            return s["step_index"]
    return None


def resume(registry: ToolRegistry, run_id: str, decision: str) -> RunResult:
    if decision not in VALID_DECISIONS:
        raise CheckpointError(f"Unknown decision: {decision!r}")

    index = pending_checkpoint(run_id)
    if index is None:
        raise CheckpointError(f"Run {run_id} has no pending checkpoint.")

    approve = decision == "approve"
    store.record_event(
        run_id,
        Event.HUMAN_DECISION,
        f"Human {'approved' if approve else 'rejected'} step {index}.",
        step_index=index,
        data={"decision": decision},
    )

    plan = load_plan(run_id)
    return Executor(registry).run(
        run_id,
        plan,
        approvals={index: approve},
        prior_outputs=prior_outputs(run_id),
    )
