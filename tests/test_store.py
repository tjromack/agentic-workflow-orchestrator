"""Phase 2: runs + plans persist and round-trip; reset clears run-state."""

from app import store
from app.planner import build_plan
from app.registry import build_registry


def test_run_and_plan_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    store.init_db()

    plan = build_plan("Brief on community solar", build_registry(), provider=None)
    run_id = store.create_run(plan.goal)
    store.save_plan(run_id, plan)

    run = store.get_run(run_id)
    assert run is not None and run["goal"] == plan.goal and run["status"] == "planned"

    saved = store.get_plan_for_run(run_id)
    assert saved["model_provider"] == "deterministic"
    assert saved["prompt_version"] == plan.prompt_version
    assert [s["tool"] for s in saved["steps"]] == [
        "retrieve_documents", "summarize_sources", "write_brief"
    ]


def test_reset_clears_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    store.init_db()
    store.create_run("temp goal")
    assert len(store.list_runs()) == 1

    store.reset_db()
    assert store.list_runs() == []
