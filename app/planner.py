"""Planner: a goal becomes an explicit, inspectable, allowlist-only plan.

The plan is a first-class object produced *before* anything runs. Each step
names a registered tool, its inputs, and its expected output. Inputs may
reference a prior step's output with ``{"$ref": "stepN.field"}`` (1-based),
resolved by the executor in Phase 3.

Two paths produce the same shape:
  * an LLM provider (Anthropic/Ollama) proposes a plan as JSON, or
  * a deterministic built-in planner emits the canonical research-to-brief plan
    when no provider is configured (so planning runs with no API key).

Either way, every referenced tool is validated against the registry — the plan
can never name a tool that is not allowlisted — and each step's ``consequential``
flag is taken from the registry, not from the model.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.providers import Provider
from app.registry import ToolRegistry, build_registry

PROMPT_VERSION = "planner/v1"
DETERMINISTIC_MODEL = "builtin-deterministic-v1"


class PlannerError(Exception):
    """Raised when a proposed plan is invalid (e.g. names a disallowed tool)."""


class DeadBranchError(PlannerError):
    """A plan has an orphaned (dead-branch) step. Unlike other planner errors this is
    *overridable*: the caller may re-plan with ``allow_dead_branches=True`` to run it anyway."""


@dataclass
class PlanStep:
    index: int  # 1-based position in the plan
    tool: str
    description: str
    inputs: dict[str, Any]
    expected_output: str
    consequential: bool = False


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep]
    model_provider: str
    model_name: str
    prompt_version: str = PROMPT_VERSION
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_steps_json(
        cls, goal: str, steps_json: str, *, model_provider: str, model_name: str,
        prompt_version: str, created_at: str,
    ) -> "Plan":
        steps = [PlanStep(**s) for s in json.loads(steps_json)]
        return cls(
            goal=goal, steps=steps, model_provider=model_provider,
            model_name=model_name, prompt_version=prompt_version, created_at=created_at,
        )


# --------------------------------------------------------------------------- #
# Validation — the allowlist boundary for plans
# --------------------------------------------------------------------------- #

def _validate_against_registry(steps: list[PlanStep], registry: ToolRegistry) -> None:
    allowed = set(registry.names())
    for step in steps:
        if step.tool not in allowed:
            raise PlannerError(
                f"Step {step.index} references tool '{step.tool}', which is not in "
                f"the registry/allowlist {sorted(allowed)}."
            )
        # The registry is authoritative for the consequential flag.
        step.consequential = registry.get(step.tool).consequential


# --------------------------------------------------------------------------- #
# Plan-graph validation — catch bad plans at PLAN time, not 3 steps in (2026-07-23)
#
# The executor already validates each step's I/O against schemas *as it runs* — but by
# then work has happened. Both failures seen on 2026-07-18 were statically detectable
# before anything ran: (1) a $ref whose produced type didn't fit the input it fed (two
# retrieves piped into one summarize -> array-of-arrays), and (2) an orphaned step whose
# output no later step consumed (a whole branch executed and was silently discarded).
# The registry exposes every tool's input/output schema at plan time, so we can resolve
# each $ref statically and reject an incoherent plan up front.
# --------------------------------------------------------------------------- #

# Same grammar the executor resolves at run time (executor._REF), so plan-time and
# run-time agree on what a reference means.
_REF_RE = re.compile(r"step(\d+)\.(\w+)")


def _schema_primary_type(schema: Any) -> str | None:
    """The JSON-Schema ``type`` as a single string, or None if unspecified/ambiguous.

    None means "don't type-check this placement" — we never reject on a type we can't
    determine, so the check has no false positives on loosely-typed inputs.
    """
    if not isinstance(schema, dict):
        return None
    t = schema.get("type")
    if isinstance(t, str):
        return t
    if isinstance(t, list) and len(t) == 1:
        return t[0]
    return None


def _walk_refs(value: Any, schema: Any):
    """Yield ``(ref_string, expected_type)`` for every $ref in an input value.

    Recurses through dicts and lists exactly as ``executor._resolve`` does, carrying the
    consuming schema down so each $ref knows the type expected at its position. The list
    case is what makes the 2026-07-18 array-of-arrays failure detectable: a $ref sitting
    as a list *element* is checked against the array's ``items`` type, not the array.
    """
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            yield value["$ref"], _schema_primary_type(schema)
        else:
            props = schema.get("properties", {}) if isinstance(schema, dict) else {}
            for k, v in value.items():
                yield from _walk_refs(v, props.get(k, {}))
    elif isinstance(value, list):
        items = schema.get("items", {}) if isinstance(schema, dict) else {}
        for v in value:
            yield from _walk_refs(v, items)


def _validate_refs(steps: list[PlanStep], registry: ToolRegistry) -> None:
    """Statically resolve and type-check every ``{"$ref": "stepN.field"}`` (Goal 1).

    Rejects, before any step runs: a malformed reference, a reference to a step that
    doesn't run earlier (forward/self/missing), a reference to an output field the
    producing tool doesn't emit, and a reference whose produced type is incompatible
    with the input position it feeds.
    """
    seen: dict[int, str] = {}  # step index -> tool, for steps already in run order
    for step in steps:
        in_props = registry.get(step.tool).input_schema.get("properties", {})
        for key, value in step.inputs.items():
            for ref, expected in _walk_refs(value, in_props.get(key, {})):
                m = _REF_RE.fullmatch(str(ref))
                if not m:
                    raise PlannerError(
                        f"Step {step.index} input '{key}' has a malformed reference "
                        f"{ref!r}; expected 'stepN.field'."
                    )
                ref_idx, field = int(m.group(1)), m.group(2)
                if ref_idx not in seen:
                    raise PlannerError(
                        f"Step {step.index} references step{ref_idx}.{field}, which does "
                        f"not run before it — a step may only use an earlier step's output."
                    )
                out_props = registry.get(seen[ref_idx]).output_schema.get("properties", {})
                if field not in out_props:
                    raise PlannerError(
                        f"Step {step.index} references step{ref_idx}.{field}, but "
                        f"'{seen[ref_idx]}' produces no '{field}' "
                        f"(its outputs are {sorted(out_props)})."
                    )
                produced = _schema_primary_type(out_props[field])
                if produced and expected and produced != expected:
                    raise PlannerError(
                        f"Step {step.index}: step{ref_idx}.{field} produces a "
                        f"'{produced}', but input '{key}' expects a '{expected}' at that "
                        f"position in '{step.tool}'. This plan would fail at run time — "
                        f"rejected before execution."
                    )
        seen[step.index] = step.tool


def _validate_no_dead_branches(
    steps: list[PlanStep], *, allow_dead_branches: bool = False
) -> None:
    """Reject plans with an orphaned step — the 2026-07-18 *silent* failure (Goal 2).

    A dead branch is a step whose output no later step consumes and which isn't the
    plan's final result — it runs, costs a model call, and is silently discarded. Seen
    live on 2026-07-23 (run ec1fb0c5): the planner summarised the 'risks' documents into
    step 4, then wrote the brief from step 3 only, throwing step 4 away.

    Exemptions, because "unconsumed output" is only *waste* for a pure transform:
      - the **terminal step** (highest index) *is* the run's result (executor.final_output);
      - a **consequential step** is an action whose side-effect is the point, so its
        return value need not be consumed.

    Rejects by default; ``allow_dead_branches=True`` is the deliberate override for the
    rare legitimate case (e.g. a fan-out where a leaf's effect is intended).
    """
    if allow_dead_branches or not steps:
        return
    consumed: set[int] = set()
    for step in steps:
        for value in step.inputs.values():
            for ref, _ in _walk_refs(value, {}):
                m = _REF_RE.fullmatch(str(ref))
                if m:
                    consumed.add(int(m.group(1)))
    terminal = max(s.index for s in steps)
    dead = [
        s.index
        for s in steps
        if s.index != terminal and not s.consequential and s.index not in consumed
    ]
    if dead:
        raise DeadBranchError(
            f"Plan has a dead branch: step(s) {dead} produce output that no later step "
            f"uses and that isn't the final result — they would run and be discarded. "
            f"Rewrite the plan so their output is consumed, or drop the step. "
            f"(Pass allow_dead_branches=True to run it anyway.)"
        )


# --------------------------------------------------------------------------- #
# Deterministic planner — canonical research-to-brief plan
# --------------------------------------------------------------------------- #

def _deterministic_steps(goal: str) -> list[PlanStep]:
    return [
        PlanStep(
            index=1,
            tool="retrieve_documents",
            description="Retrieve relevant source documents for the question.",
            inputs={"query": goal, "k": 5},
            expected_output="Up to k documents (id, title, source, url, snippet).",
        ),
        PlanStep(
            index=2,
            tool="summarize_sources",
            description="Summarize the retrieved documents into a cited outline.",
            inputs={"question": goal, "documents": {"$ref": "step1.documents"}},
            expected_output="An outline (headings, points, source_ids) and key findings.",
        ),
        PlanStep(
            index=3,
            tool="write_brief",
            description="Write the final cited brief from the approved outline.",
            inputs={
                "question": goal,
                "outline": {"$ref": "step2.outline"},
                "documents": {"$ref": "step1.documents"},
            },
            expected_output="A cited markdown brief and a list of citations.",
        ),
    ]


# --------------------------------------------------------------------------- #
# LLM planner
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = """\
You are a planner for a guarded workflow engine. Decompose the user's goal into
an ordered list of steps. You may ONLY use the tools provided below — never
invent a tool. Output ONLY a JSON object, no prose, of the form:

{"steps": [
  {"index": 1, "tool": "<tool name>", "description": "<what this step does>",
   "inputs": { ... }, "expected_output": "<what it should produce>"}
]}

Rules:
- Use only the listed tool names. Inputs must match each tool's input_schema.
- To pass a prior step's output as an input, use {"$ref": "stepN.field"} where N
  is the 1-based step index and field is a key from that step's output_schema.
- Keep the plan minimal and ordered; do not include an index that skips numbers.
"""


def _tools_brief(registry: ToolRegistry) -> str:
    lines = []
    for spec in registry.specs():
        lines.append(f"- {spec['name']}: {spec['description']}")
        lines.append(f"    input_schema: {json.dumps(spec['input_schema'])}")
        lines.append(f"    output_schema: {json.dumps(spec['output_schema'])}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]
    return json.loads(text)


def _llm_steps(goal: str, registry: ToolRegistry, provider: Provider) -> list[PlanStep]:
    user = f"Goal: {goal}\n\nAvailable tools:\n{_tools_brief(registry)}"
    raw = provider.complete(_SYSTEM_PROMPT, user)
    data = _extract_json(raw)
    steps = []
    for i, item in enumerate(data.get("steps", []), start=1):
        steps.append(
            PlanStep(
                index=int(item.get("index", i)),
                tool=item["tool"],
                description=item.get("description", ""),
                inputs=item.get("inputs", {}),
                expected_output=item.get("expected_output", ""),
            )
        )
    if not steps:
        raise PlannerError("Provider returned no steps.")
    return steps


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def build_plan(
    goal: str,
    registry: ToolRegistry,
    provider: Provider | None = None,
    *,
    allow_dead_branches: bool = False,
) -> Plan:
    """Produce a validated plan for ``goal`` using only allowlisted tools.

    With no provider, or if the provider fails, falls back to the deterministic
    plan so the demo always produces something inspectable.

    ``allow_dead_branches`` overrides the orphaned-step rejection (see
    ``_validate_no_dead_branches``) for the rare case where an unconsumed leaf is intended.
    """
    goal = goal.strip()
    if not goal:
        raise PlannerError("Goal must not be empty.")

    if provider is None:
        steps = _deterministic_steps(goal)
        model_provider, model_name = "deterministic", DETERMINISTIC_MODEL
    else:
        fallback_reason: str | None = None
        try:
            steps = _llm_steps(goal, registry, provider)
        except Exception as exc:  # noqa: BLE001 — provider unavailable / returned no usable steps
            steps, fallback_reason = _deterministic_steps(goal), type(exc).__name__
        else:
            # The allow-list is a HARD guardrail: a disallowed/unregistered tool is rejected, never
            # swapped for a safe plan — surfacing the attempt is the point.
            _validate_against_registry(steps, registry)
            # A type-mismatched reference means the model wired otherwise-valid tools together
            # incorrectly. That is recoverable: fall back to the (always-valid) deterministic plan
            # rather than surface a raw validation error to the user.
            try:
                _validate_refs(steps, registry)
            except PlannerError as exc:
                steps, fallback_reason = _deterministic_steps(goal), type(exc).__name__

        if fallback_reason is None:
            model_provider, model_name = provider.name, provider.model
        else:
            model_provider = "deterministic"
            model_name = f"{DETERMINISTIC_MODEL} (fallback: {fallback_reason})"

    _validate_against_registry(steps, registry)
    _validate_refs(steps, registry)
    _validate_no_dead_branches(steps, allow_dead_branches=allow_dead_branches)
    return Plan(
        goal=goal,
        steps=steps,
        model_provider=model_provider,
        model_name=model_name,
    )


def main(argv: list[str]) -> int:
    goal = " ".join(argv) or "Write a short research brief on urban green roofs."
    plan = build_plan(goal, build_registry(), provider=None)
    print(json.dumps(plan.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
