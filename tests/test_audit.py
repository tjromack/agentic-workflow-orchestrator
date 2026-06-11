"""Phase 5 gate: any completed run can be inspected and replayed from the audit
log — plan, tool inputs/outputs, guardrail events, human decisions, timings."""

from app import audit, checkpoints, store
from app.executor import Event, Executor
from app.planner import build_plan
from app.registry import build_registry


def _completed_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "audit.db"))
    store.init_db()
    reg = build_registry()
    plan = build_plan("Brief on urban green roofs", reg, provider=None)
    run_id = store.create_run(plan.goal)
    store.save_plan(run_id, plan)
    Executor(reg).run(run_id, plan)  # pauses at checkpoint
    checkpoints.resume(reg, run_id, "approve")  # completes
    return run_id


def test_trace_reconstructs_full_run(tmp_path, monkeypatch):
    run_id = _completed_run(tmp_path, monkeypatch)
    trace = audit.get_trace(run_id)

    assert trace["run"]["status"] == "completed"
    # plan + tool inputs/outputs present for every step.
    assert [s["tool"] for s in trace["steps"]] == [
        "retrieve_documents", "summarize_sources", "write_brief"
    ]
    assert all(s["resolved_inputs"] is not None for s in trace["steps"])
    assert all(s["output"] is not None for s in trace["steps"])
    # human decision captured.
    assert trace["decisions"] and trace["decisions"][0]["data"]["decision"] == "approve"
    # the brief is recoverable from the trace.
    assert trace["brief"] and trace["brief"].startswith("# ")


def test_trace_has_timings_and_event_order(tmp_path, monkeypatch):
    run_id = _completed_run(tmp_path, monkeypatch)
    trace = audit.get_trace(run_id)

    assert trace["timings"]["total_ms"] is not None
    # events carry monotonic relative offsets and the checkpoint precedes the decision.
    kinds = [e["kind"] for e in trace["events"]]
    assert kinds[0] == Event.STEP_STARTED
    assert kinds.index(Event.CHECKPOINT_REQUIRED) < kinds.index(Event.HUMAN_DECISION)
    assert kinds[-1] == Event.RUN_COMPLETED


def test_unknown_run_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "audit.db"))
    store.init_db()
    assert audit.get_trace("does-not-exist") is None


def test_list_runs_includes_the_run(tmp_path, monkeypatch):
    run_id = _completed_run(tmp_path, monkeypatch)
    assert run_id in {r["id"] for r in audit.list_runs()}
