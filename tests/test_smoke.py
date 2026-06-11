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
