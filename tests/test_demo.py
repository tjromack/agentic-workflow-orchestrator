"""Phase 6: the lead research-to-brief demo, end to end, plus the empty/error
states that keep the demo graceful from a clean seed."""

import pytest

from app import audit, checkpoints, store
from app.executor import Event, Executor, RunStatus, StepStatus
from app.planner import PlannerError, build_plan
from app.registry import build_registry
from app.tools import retrieve


def _seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "demo.db"))
    store.reset_db()
    return build_registry()


def test_research_to_brief_demo_end_to_end(tmp_path, monkeypatch):
    reg = _seeded(tmp_path, monkeypatch)
    plan = build_plan(
        "Write a short research brief on the benefits and risks of urban green roofs.",
        reg, provider=None,
    )
    run_id = store.create_run(plan.goal)
    store.save_plan(run_id, plan)

    # Pauses at the consequential write_brief checkpoint.
    assert Executor(reg).run(run_id, plan).status == RunStatus.AWAITING_CHECKPOINT
    # Approving the outline produces the cited brief.
    result = checkpoints.resume(reg, run_id, "approve")
    assert result.status == RunStatus.COMPLETED

    trace = audit.get_trace(run_id)
    assert trace["brief"].startswith("# ")
    assert "## Sources" in trace["brief"]
    assert trace["steps"][-1]["output"]["citations"]


def test_off_corpus_goal_trips_a_guardrail(tmp_path, monkeypatch):
    """An out-of-corpus question retrieves nothing; the empty result is caught by
    the next step's input schema, not silently summarized."""
    reg = _seeded(tmp_path, monkeypatch)
    assert retrieve.get_tool().handler({"query": "quantum teleportation hardware"})[
        "documents"
    ] == []

    plan = build_plan("Write a brief on quantum teleportation hardware", reg, None)
    run_id = store.create_run(plan.goal)
    store.save_plan(run_id, plan)
    result = Executor(reg).run(run_id, plan, approvals={3: True})

    assert result.status == RunStatus.FAILED
    assert result.steps[1].status == StepStatus.FAILED
    assert Event.VALIDATION_FAILURE in [e.kind for e in result.events]


def test_empty_goal_is_rejected_gracefully(tmp_path, monkeypatch):
    reg = _seeded(tmp_path, monkeypatch)
    with pytest.raises(PlannerError):
        build_plan("   ", reg, provider=None)
