"""`make seed` / `make reset` — initialize storage, register the demo tools,
and load sample goals, then report.

  python -m app.seed            initialize DB (if needed), register, validate
  python -m app.seed --reset    drop run-state first for a clean demo
"""

from __future__ import annotations

import json
import sys

from app import store
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


def main(argv: list[str]) -> int:
    reset = "--reset" in argv
    if reset:
        store.reset_db()
        print("Run-state cleared.")
    else:
        store.init_db()

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

    print("\nSeed complete: storage ready, tools registered, goals validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
