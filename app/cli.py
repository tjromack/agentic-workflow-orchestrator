"""CLI demo: plan a goal and run it end-to-end (auto-approving the checkpoint).

  python -m app.cli "Write a short research brief on urban green roofs."

Auto-approval here is an explicit CLI convenience to demonstrate full execution;
the web app and the default executor pause at consequential steps.
"""

from __future__ import annotations

import sys

from app import store
from app.config import load_settings
from app.executor import Executor
from app.planner import build_plan
from app.providers import make_provider
from app.registry import build_registry


def main(argv: list[str]) -> int:
    goal = " ".join(argv) or "Write a short research brief on urban green roofs."
    registry = build_registry()
    store.init_db()

    plan = build_plan(goal, registry, make_provider(load_settings()))
    run_id = store.create_run(goal)
    store.save_plan(run_id, plan)

    # Approve every consequential step so the demo runs to completion.
    approvals = {s.index: True for s in plan.steps if s.consequential}
    result = Executor(registry).run(run_id, plan, approvals=approvals)

    print(f"run {run_id} — status: {result.status}\n")
    for sr in result.steps:
        print(f"  step {sr.index} {sr.tool}: {sr.status} ({sr.attempts} attempt(s))")
    print("\nGuardrail / trace events:")
    for ev in result.events:
        where = f" [step {ev.step_index}]" if ev.step_index else ""
        print(f"  - {ev.kind}{where}: {ev.message}")

    if result.final_output and "brief_markdown" in result.final_output:
        print("\n--- BRIEF ---\n")
        print(result.final_output["brief_markdown"])
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
