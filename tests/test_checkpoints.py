"""Phase 4 gate: a run halts at a checkpoint and only proceeds on explicit
approval; the decision is recorded; rejection halts the run."""

import time

import pytest

from app import audit, checkpoints, store
from app.checkpoints import CheckpointError
from app.executor import Event, Executor, RunStatus, StepStatus
from app.planner import build_plan
from app.registry import build_registry


def _start_paused_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "cp.db"))
    store.init_db()
    reg = build_registry()
    plan = build_plan("Brief on urban green roofs", reg, provider=None)
    run_id = store.create_run(plan.goal)
    store.save_plan(run_id, plan)
    result = Executor(reg).run(run_id, plan)  # no approval -> pause
    assert result.status == RunStatus.AWAITING_CHECKPOINT
    return reg, run_id


def test_run_pauses_then_completes_on_approval(tmp_path, monkeypatch):
    reg, run_id = _start_paused_run(tmp_path, monkeypatch)
    assert checkpoints.pending_checkpoint(run_id) == 3

    result = checkpoints.resume(reg, run_id, "approve")

    assert result.status == RunStatus.COMPLETED
    assert store.get_run(run_id)["status"] == RunStatus.COMPLETED
    # The consequential step actually ran this time.
    steps = {s["step_index"]: s for s in store.get_steps(run_id)}
    assert steps[3]["status"] == StepStatus.SUCCEEDED
    # The human decision is in the audit trace.
    kinds = [e["kind"] for e in store.get_events(run_id)]
    assert Event.HUMAN_DECISION in kinds
    assert kinds.count(Event.CHECKPOINT_REQUIRED) == 1


def test_step_timing_separates_human_wait_from_execution(tmp_path, monkeypatch):
    # Regression (2026-07-18): a consequential step's duration counted the human-checkpoint wait
    # (199,556 ms once). Now `duration_ms` is execution-only (from STEP_STARTED) and the wait is `waiting_ms`.
    reg, run_id = _start_paused_run(tmp_path, monkeypatch)
    time.sleep(0.06)  # simulate a human deliberating at the checkpoint
    checkpoints.resume(reg, run_id, "approve")

    steps = {s["index"]: s for s in audit.get_trace(run_id)["steps"]}
    cp = steps[3]  # the consequential step that paused for approval
    assert cp["waiting_ms"] is not None and cp["waiting_ms"] >= 50   # the wait is captured…
    assert cp["duration_ms"] < cp["waiting_ms"]                       # …and NOT billed as execution
    # a non-consequential step never paused -> clean 0 wait (no event/row-ordering noise)
    assert steps[1]["waiting_ms"] == 0


def test_rejection_halts_and_is_recorded(tmp_path, monkeypatch):
    reg, run_id = _start_paused_run(tmp_path, monkeypatch)

    result = checkpoints.resume(reg, run_id, "reject")

    assert result.status == RunStatus.HALTED
    steps = {s["step_index"]: s for s in store.get_steps(run_id)}
    assert steps[3]["status"] == StepStatus.REJECTED
    decisions = [
        e for e in store.get_events(run_id) if e["kind"] == Event.HUMAN_DECISION
    ]
    assert decisions and "rejected" in decisions[0]["message"]


def test_resume_carries_prior_outputs_without_rerunning(tmp_path, monkeypatch):
    reg, run_id = _start_paused_run(tmp_path, monkeypatch)
    checkpoints.resume(reg, run_id, "approve")

    # retrieve + summarize each started exactly once (not re-run on resume).
    started = [
        e for e in store.get_events(run_id) if e["kind"] == Event.STEP_STARTED
    ]
    started_indexes = sorted(e["step_index"] for e in started)
    assert started_indexes == [1, 2, 3]  # step 3 started only after approval


def test_resume_without_pending_checkpoint_errors(tmp_path, monkeypatch):
    reg, run_id = _start_paused_run(tmp_path, monkeypatch)
    checkpoints.resume(reg, run_id, "approve")  # completes the run
    with pytest.raises(CheckpointError):
        checkpoints.resume(reg, run_id, "approve")


def test_invalid_decision_rejected(tmp_path, monkeypatch):
    reg, run_id = _start_paused_run(tmp_path, monkeypatch)
    with pytest.raises(CheckpointError):
        checkpoints.resume(reg, run_id, "maybe")
