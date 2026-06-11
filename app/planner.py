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
    goal: str, registry: ToolRegistry, provider: Provider | None = None
) -> Plan:
    """Produce a validated plan for ``goal`` using only allowlisted tools.

    With no provider, or if the provider fails, falls back to the deterministic
    plan so the demo always produces something inspectable.
    """
    goal = goal.strip()
    if not goal:
        raise PlannerError("Goal must not be empty.")

    if provider is None:
        steps = _deterministic_steps(goal)
        model_provider, model_name = "deterministic", DETERMINISTIC_MODEL
    else:
        try:
            steps = _llm_steps(goal, registry, provider)
            model_provider, model_name = provider.name, provider.model
        except Exception as exc:  # noqa: BLE001 — resilient demo fallback
            steps = _deterministic_steps(goal)
            model_provider = "deterministic"
            model_name = f"{DETERMINISTIC_MODEL} (fallback: {type(exc).__name__})"

    _validate_against_registry(steps, registry)
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
