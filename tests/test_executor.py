"""Phase 3 gate: a plan runs end to end on seeded tools, and a deliberately bad
step is caught (not silently passed). Guardrail events are surfaced."""

import pytest

from app.executor import Event, Executor, RunStatus, StepStatus
from app.planner import Plan, PlanStep, build_plan
from app.registry import Tool, build_registry


def _kinds(result):
    return [e.kind for e in result.events]


def test_end_to_end_with_approval_produces_brief():
    reg = build_registry()
    plan = build_plan("Brief on urban green roofs", reg, provider=None)
    result = Executor(reg, persist=False).run("r1", plan, approvals={3: True})

    assert result.status == RunStatus.COMPLETED
    assert [s.status for s in result.steps] == [StepStatus.SUCCEEDED] * 3
    assert "brief_markdown" in result.final_output
    assert Event.RUN_COMPLETED in _kinds(result)


def test_consequential_step_pauses_without_approval():
    reg = build_registry()
    plan = build_plan("Brief on urban green roofs", reg, provider=None)
    result = Executor(reg, persist=False).run("r2", plan)  # no approvals

    assert result.status == RunStatus.AWAITING_CHECKPOINT
    # retrieve + summarize ran; write_brief is paused, not executed.
    assert result.steps[0].status == StepStatus.SUCCEEDED
    assert result.steps[1].status == StepStatus.SUCCEEDED
    assert result.steps[-1].status == StepStatus.AWAITING_CHECKPOINT
    assert Event.CHECKPOINT_REQUIRED in _kinds(result)
    assert "write_brief" not in result.outputs.get(3, {})


def test_rejection_halts_the_run():
    reg = build_registry()
    plan = build_plan("Brief on urban green roofs", reg, provider=None)
    result = Executor(reg, persist=False).run("r3", plan, approvals={3: False})

    assert result.status == RunStatus.HALTED
    assert result.steps[-1].status == StepStatus.REJECTED
    assert Event.REJECTED in _kinds(result)


def test_bad_output_is_caught_not_passed():
    """A tool whose output violates its schema must halt with a validation event."""
    reg = build_registry()
    bad = Tool(
        name="broken",
        description="returns schema-invalid output",
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        handler=lambda inp: {"value": 123},  # wrong type
    )
    reg.register(bad)
    plan = Plan(
        goal="trip a guardrail",
        steps=[PlanStep(1, "broken", "bad step", {}, "nothing valid")],
        model_provider="deterministic",
        model_name="t",
    )
    result = Executor(reg, persist=False).run("r4", plan)

    assert result.status == RunStatus.FAILED
    assert result.steps[0].status == StepStatus.FAILED
    assert Event.VALIDATION_FAILURE in _kinds(result)


def test_disallowed_tool_is_halted():
    reg = build_registry()
    plan = Plan(
        goal="call a tool that isn't registered",
        steps=[PlanStep(1, "not_registered", "nope", {}, "n/a")],
        model_provider="deterministic",
        model_name="t",
    )
    result = Executor(reg, persist=False).run("r5", plan)
    assert result.status == RunStatus.FAILED
    assert Event.DISALLOWED_TOOL in _kinds(result)


def test_step_budget_halts_oversized_plan():
    reg = build_registry()
    steps = [PlanStep(i, "retrieve_documents", "x", {"query": "q"}, "docs")
             for i in range(1, 6)]
    plan = Plan("too big", steps, "deterministic", "t")
    result = Executor(reg, persist=False, max_steps=3).run("r6", plan)
    assert result.status == RunStatus.HALTED
    assert Event.BUDGET_EXCEEDED in _kinds(result)


def test_retry_then_succeed():
    """A transient failure retries; success on the second attempt completes."""
    reg = build_registry()
    state = {"calls": 0}

    def flaky(inp):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("transient")
        return {"ok": True}

    reg.register(Tool(
        name="flaky",
        description="fails once then succeeds",
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}},
                       "required": ["ok"]},
        handler=flaky,
    ))
    plan = Plan("flaky", [PlanStep(1, "flaky", "x", {}, "ok")], "deterministic", "t")
    result = Executor(reg, persist=False, max_attempts=2).run("r7", plan)

    assert result.status == RunStatus.COMPLETED
    assert result.steps[0].attempts == 2
    assert Event.RETRY in _kinds(result)


def test_persistence_records_steps_and_events(tmp_path, monkeypatch):
    from app import store

    monkeypatch.setenv("DB_PATH", str(tmp_path / "exec.db"))
    store.init_db()
    reg = build_registry()
    plan = build_plan("Brief on community solar", reg, provider=None)
    run_id = store.create_run(plan.goal)
    store.save_plan(run_id, plan)

    Executor(reg).run(run_id, plan, approvals={3: True})

    assert store.get_run(run_id)["status"] == RunStatus.COMPLETED
    assert len(store.get_steps(run_id)) == 3
    assert any(e["kind"] == Event.RUN_COMPLETED for e in store.get_events(run_id))
