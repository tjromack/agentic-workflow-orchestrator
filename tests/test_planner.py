"""Phase 2 gate: a goal produces a sensible, inspectable plan that references
only allowlisted tools; the plan persists with model + prompt version."""

import json

import pytest

from app.planner import PROMPT_VERSION, PlannerError, PlanStep, build_plan
from app.registry import build_registry


def test_deterministic_plan_is_ordered_and_allowlisted():
    reg = build_registry()
    plan = build_plan("Brief on urban green roofs", reg, provider=None)

    tools = [s.tool for s in plan.steps]
    assert tools == ["retrieve_documents", "summarize_sources", "write_brief"]
    assert [s.index for s in plan.steps] == [1, 2, 3]
    # Every referenced tool is in the allowlist.
    assert set(tools) <= set(reg.names())
    # consequential flag comes from the registry.
    assert plan.steps[-1].consequential is True
    assert plan.steps[0].consequential is False
    # model + prompt version recorded.
    assert plan.model_provider == "deterministic"
    assert plan.prompt_version == PROMPT_VERSION


def test_plan_rejects_disallowed_tool():
    reg = build_registry()

    class FakeProvider:
        name = "fake"
        model = "fake-1"

        def complete(self, system, user):
            return json.dumps(
                {"steps": [{"index": 1, "tool": "rm_rf", "inputs": {},
                            "expected_output": "boom"}]}
            )

    with pytest.raises(PlannerError):
        build_plan("do something bad", reg, provider=FakeProvider())


def test_llm_plan_parsed_and_validated():
    reg = build_registry()

    class FakeProvider:
        name = "fake"
        model = "fake-1"

        def complete(self, system, user):
            return (
                "```json\n"
                + json.dumps(
                    {
                        "steps": [
                            {"index": 1, "tool": "retrieve_documents",
                             "description": "find docs",
                             "inputs": {"query": "green roofs", "k": 3},
                             "expected_output": "docs"},
                        ]
                    }
                )
                + "\n```"
            )

    plan = build_plan("research green roofs", reg, provider=FakeProvider())
    assert plan.model_provider == "fake"
    assert plan.steps[0].tool == "retrieve_documents"


def test_empty_goal_rejected():
    with pytest.raises(PlannerError):
        build_plan("   ", build_registry(), provider=None)
