"""`make seed` — build the registry and load sample goals, then report.

Phase 1 has no database yet, so seeding registers the demo tools (proving the
allowlist and schema validation) and validates the sample goals file. Run-state
clearing is added with persistence in a later phase.
"""

from __future__ import annotations

import json
import sys

from app.paths import SEED_GOALS
from app.registry import build_registry


def load_goals() -> list[dict]:
    with SEED_GOALS.open(encoding="utf-8") as fh:
        data = json.load(fh)
    goals = data.get("goals", [])
    if not goals:
        raise ValueError(f"No goals found in {SEED_GOALS}")
    for goal in goals:
        for field in ("id", "question"):
            if field not in goal:
                raise ValueError(f"Goal missing '{field}': {goal!r}")
    return goals


def main() -> int:
    registry = build_registry()

    print("Registered tools (allowlist):")
    for spec in registry.specs():
        flag = "  [consequential]" if spec["consequential"] else ""
        print(f"  - {spec['name']}{flag}")
        print(f"      {spec['description']}")

    goals = load_goals()
    print(f"\nSample goals ({len(goals)}):")
    for goal in goals:
        print(f"  - {goal['id']}: {goal['question']}")

    print("\nSeed complete: tools registered, goals validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
