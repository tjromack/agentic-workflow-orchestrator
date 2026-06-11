"""Phase 0 smoke tests: the app boots and the base template renders."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_index_renders():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Agentic Workflow Orchestrator" in resp.text


def test_runs_list_renders():
    resp = client.get("/runs")
    assert resp.status_code == 200
    assert "audit log" in resp.text.lower()


def test_empty_goal_shows_error_card_not_500():
    resp = client.post("/run", data={"goal": "   "})
    assert resp.status_code == 200
    assert "Couldn't proceed" in resp.text


def test_resume_unknown_run_is_graceful():
    resp = client.post("/resume", data={"run_id": "nope", "decision": "approve"})
    assert resp.status_code == 200
    assert "Couldn't proceed" in resp.text


def test_run_view_unknown_returns_404():
    assert client.get("/runs/does-not-exist").status_code == 404
