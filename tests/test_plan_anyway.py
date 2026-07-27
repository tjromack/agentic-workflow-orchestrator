"""The "plan anyway" affordance (2026-07-23 backlog).

Plan-graph validation correctly rejects a dead-branch plan — but only the *live* planner ever produces
one (the deterministic fallback is always coherent), so the web demo could dead-end with no way forward.
A dead-branch rejection now offers a deliberate override button that re-plans with allow_dead_branches=True.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main
from app.planner import DeadBranchError, PlannerError, build_plan


def test_dead_branch_error_is_an_overridable_planner_error():
    assert issubclass(DeadBranchError, PlannerError)


def test_plan_anyway_button_appears_then_overrides(monkeypatch):
    real = build_plan

    def fake_build(goal, registry, provider=None, *, allow_dead_branches=False):
        # Simulate the live planner emitting a dead branch unless the override is set.
        if not allow_dead_branches:
            raise DeadBranchError(
                "Plan has a dead branch: step(s) [4] produce output no later step uses. "
                "(Pass allow_dead_branches=True to run it anyway.)"
            )
        return real(goal, registry, provider=None)  # coherent deterministic plan

    monkeypatch.setattr(main, "build_plan", fake_build)
    client = TestClient(main.app)

    # 1) the dead-branch rejection surfaces the override button (not a dead-end)
    r = client.post("/plan", data={"goal": "Brief on urban green roofs"})
    assert r.status_code == 200
    assert "Plan anyway" in r.text
    assert 'name="allow_dead_branches"' in r.text and 'value="true"' in r.text

    # 2) clicking it re-plans with the override and renders a plan (no error card)
    r2 = client.post("/plan", data={"goal": "Brief on urban green roofs", "allow_dead_branches": "true"})
    assert r2.status_code == 200
    assert "Couldn't proceed" not in r2.text and "Plan anyway" not in r2.text
    assert "write_brief" in r2.text  # a real plan rendered


def test_non_dead_branch_error_offers_no_override(monkeypatch):
    def fake_build(goal, registry, provider=None, *, allow_dead_branches=False):
        raise PlannerError("Plan names a disallowed tool 'delete_everything'.")

    monkeypatch.setattr(main, "build_plan", fake_build)
    client = TestClient(main.app)
    r = client.post("/plan", data={"goal": "do something bad"})
    assert "Couldn't proceed" in r.text
    assert "Plan anyway" not in r.text  # only dead-branch is overridable
