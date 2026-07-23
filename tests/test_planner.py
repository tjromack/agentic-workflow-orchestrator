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


# --- Plan-graph validation (2026-07-23): catch bad plans at plan time ---------
#
# Both failures reproduced below actually happened on 2026-07-18 with a live LLM
# planner; here they are pinned as fixtures so the static checks can't regress.


def _steps(*specs):
    """(index, tool, inputs) tuples -> PlanStep list."""
    return [
        PlanStep(index=i, tool=t, description=t, inputs=inp, expected_output="x")
        for (i, t, inp) in specs
    ]


def test_ref_shape_mismatch_is_rejected_at_plan_time():
    """The 2026-07-18 'loud' failure: two retrieves piped into one summarize as a
    list makes `documents` an array-of-arrays. It used to halt 3 steps in; now it's
    rejected before anything runs."""
    from app.planner import _validate_refs

    reg = build_registry()
    bad = _steps(
        (1, "retrieve_documents", {"query": "benefits", "k": 8}),
        (2, "retrieve_documents", {"query": "risks", "k": 8}),
        (3, "summarize_sources", {
            "question": "q",
            "documents": [{"$ref": "step1.documents"}, {"$ref": "step2.documents"}],
        }),
    )
    with pytest.raises(PlannerError) as exc:
        _validate_refs(bad, reg)
    assert "array" in str(exc.value) and "object" in str(exc.value)


def test_forward_reference_is_rejected():
    from app.planner import _validate_refs

    reg = build_registry()
    bad = _steps((1, "summarize_sources", {"question": "q", "documents": {"$ref": "step2.documents"}}))
    with pytest.raises(PlannerError, match="does not run before it"):
        _validate_refs(bad, reg)


def test_reference_to_missing_output_field_is_rejected():
    from app.planner import _validate_refs

    reg = build_registry()
    bad = _steps(
        (1, "retrieve_documents", {"query": "q"}),
        (2, "summarize_sources", {"question": "q", "documents": {"$ref": "step1.nonesuch"}}),
    )
    with pytest.raises(PlannerError, match="produces no 'nonesuch'"):
        _validate_refs(bad, reg)


def test_wellformed_refs_pass_and_deterministic_plan_still_validates():
    """No false positives: the shipped happy-path plan must sail through."""
    reg = build_registry()
    # build_plan runs the ref validation internally; a raise here would fail the test.
    plan = build_plan("Brief on urban green roofs", reg, provider=None)
    assert [s.tool for s in plan.steps] == ["retrieve_documents", "summarize_sources", "write_brief"]


# --- Dead-branch detection (2026-07-23, Goal 2): the *silent* failure -----------
#
# Reproduces the plan a live planner produced on 2026-07-23 (run ec1fb0c5): it
# summarised the 'risks' docs into step 4, then wrote the brief from step 3 only,
# so step 4 ran and was discarded. Schema-valid, but incoherent.


def test_orphaned_step_is_rejected():
    from app.planner import _validate_against_registry, _validate_no_dead_branches

    reg = build_registry()
    steps = _steps(
        (1, "retrieve_documents", {"query": "benefits", "k": 5}),
        (2, "retrieve_documents", {"query": "risks", "k": 5}),
        (3, "summarize_sources", {"question": "q", "documents": {"$ref": "step1.documents"}}),
        (4, "summarize_sources", {"question": "q", "documents": {"$ref": "step2.documents"}}),  # orphan
        (5, "write_brief", {
            "question": "q",
            "outline": {"$ref": "step3.outline"},
            "documents": {"$ref": "step1.documents"},
        }),
    )
    _validate_against_registry(steps, reg)  # sets .consequential from the registry
    with pytest.raises(PlannerError, match=r"dead branch.*\[4\]"):
        _validate_no_dead_branches(steps)


def test_allow_dead_branches_overrides_the_rejection():
    from app.planner import _validate_against_registry, _validate_no_dead_branches

    reg = build_registry()
    steps = _steps(
        (1, "retrieve_documents", {"query": "b", "k": 5}),
        (2, "retrieve_documents", {"query": "r", "k": 5}),
        (3, "summarize_sources", {"question": "q", "documents": {"$ref": "step1.documents"}}),
        (4, "summarize_sources", {"question": "q", "documents": {"$ref": "step2.documents"}}),
        (5, "write_brief", {"question": "q", "outline": {"$ref": "step3.outline"},
                            "documents": {"$ref": "step1.documents"}}),
    )
    _validate_against_registry(steps, reg)
    _validate_no_dead_branches(steps, allow_dead_branches=True)  # must not raise


def test_consequential_leaf_is_not_a_dead_branch():
    """A consequential step is an action; its unconsumed output is not waste."""
    from app.planner import _validate_against_registry, _validate_no_dead_branches

    reg = build_registry()
    steps = _steps(
        (1, "retrieve_documents", {"query": "q"}),
        (2, "summarize_sources", {"question": "q", "documents": {"$ref": "step1.documents"}}),
        (3, "write_brief", {"question": "q", "outline": {"$ref": "step2.outline"},
                           "documents": {"$ref": "step1.documents"}}),
    )
    _validate_against_registry(steps, reg)
    _validate_no_dead_branches(steps)  # write_brief (consequential + terminal) is fine
