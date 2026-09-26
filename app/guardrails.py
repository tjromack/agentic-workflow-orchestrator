"""Publish the orchestrator's guardrail behaviour — the safety story, measured.

Each guardrail is exercised on a constructed plan, and the event it fires plus the run outcome are printed. This is the
evidence behind the design claim: an agent runs one step at a time behind a **step budget**, **retry-then-halt**, a
**human checkpoint** on consequential steps, **schema validation** on every tool output, and an **allow-listed tool
registry**. Nothing here calls a model — the guardrails are deterministic control-flow, exercised on deterministic tools.

Run: `make guardrails` (python -m app.guardrails).
"""
from __future__ import annotations

import os
import tempfile

from app.executor import Event, Executor, RunStatus, StepStatus
from app.planner import Plan, PlanStep, build_plan
from app.registry import Tool, build_registry

GOAL = "Brief on urban green roofs"


def _events(result) -> set[str]:
    return {e.kind for e in result.events}


def _happy():
    reg = build_registry()
    plan = build_plan(GOAL, reg, provider=None)
    r = Executor(reg, persist=False).run("g-happy", plan, approvals={3: True})
    return ("Normal run (checkpoint approved)", "—", r.status, len([s for s in r.steps if s.status == StepStatus.SUCCEEDED]),
            Event.RUN_COMPLETED in _events(r), r.status == RunStatus.COMPLETED)


def _checkpoint():
    reg = build_registry()
    plan = build_plan(GOAL, reg, provider=None)
    r = Executor(reg, persist=False).run("g-cp", plan)  # no approval
    return ("Consequential step, no approval", "human checkpoint", r.status,
            Event.CHECKPOINT_REQUIRED in _events(r), r.status == RunStatus.AWAITING_CHECKPOINT)


def _rejected():
    reg = build_registry()
    plan = build_plan(GOAL, reg, provider=None)
    r = Executor(reg, persist=False).run("g-rej", plan, approvals={3: False})
    return ("Consequential step, rejected", "human checkpoint", r.status,
            Event.REJECTED in _events(r), r.status == RunStatus.HALTED)


def _budget():
    reg = build_registry()
    steps = [PlanStep(i, "retrieve_documents", "x", {"query": "q"}, "docs") for i in range(1, 6)]
    plan = Plan("oversized plan", steps, "deterministic", "t")
    r = Executor(reg, persist=False, max_steps=3).run("g-bud", plan)
    return ("Plan over the step budget (5 > 3)", "step budget", r.status,
            Event.BUDGET_EXCEEDED in _events(r), r.status == RunStatus.HALTED)


def _retry_halt():
    reg = build_registry()

    def always_fail(inp):
        raise RuntimeError("tool keeps failing")

    reg.register(Tool(name="flaky", description="always fails",
                      input_schema={"type": "object", "additionalProperties": True},
                      output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                      handler=always_fail))
    plan = Plan("persistent failure", [PlanStep(1, "flaky", "x", {}, "ok")], "deterministic", "t")
    r = Executor(reg, persist=False, max_attempts=2).run("g-retry", plan)
    return ("Tool fails every attempt (retry x2)", "retry-then-halt", r.status,
            Event.RETRY in _events(r), r.status == RunStatus.FAILED)


def _validation():
    reg = build_registry()
    reg.register(Tool(name="broken", description="schema-invalid output",
                      input_schema={"type": "object", "additionalProperties": True},
                      output_schema={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                      handler=lambda inp: {"value": 123}))  # wrong type
    plan = Plan("bad output", [PlanStep(1, "broken", "x", {}, "valid")], "deterministic", "t")
    r = Executor(reg, persist=False).run("g-val", plan)
    return ("Tool output violates its schema", "schema validation", r.status,
            Event.VALIDATION_FAILURE in _events(r), r.status == RunStatus.FAILED)


def _disallowed():
    reg = build_registry()
    plan = Plan("unknown tool", [PlanStep(1, "not_registered", "x", {}, "n/a")], "deterministic", "t")
    r = Executor(reg, persist=False).run("g-dis", plan)
    return ("Plan calls an unregistered tool", "allow-listed tools", r.status,
            Event.DISALLOWED_TOOL in _events(r), r.status == RunStatus.FAILED)


def _plan_metrics():
    """Run one persisted happy path in a temp DB; return (n_steps, total_ms, [per-step ms]) from the audit trace."""
    from app import audit, store
    with tempfile.TemporaryDirectory() as d:
        os.environ["DB_PATH"] = os.path.join(d, "gr.db")
        store.init_db()
        reg = build_registry()
        plan = build_plan(GOAL, reg, provider=None)
        run_id = store.create_run(plan.goal)
        store.save_plan(run_id, plan)
        Executor(reg).run(run_id, plan, approvals={3: True})
        trace = audit.get_trace(run_id) or {}
        steps = trace.get("steps", [])
        per_step = [s.get("duration_ms") for s in steps]
        total = (trace.get("timings") or {}).get("total_ms")
        return len(steps), total, per_step


def main() -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    rows = [
        ("Normal run (checkpoint approved)", "—", "completed", "runs to completion (3/3 steps)"),
    ]
    # behaviour checks (each returns ..., event_fired, outcome_ok)
    checks = [_checkpoint(), _rejected(), _budget(), _retry_halt(), _validation(), _disallowed()]
    happy = _happy()
    ok_happy = happy[-1] and happy[-2]

    print("Guardrail behaviour — the orchestrator's safety story, exercised\n")
    print(f"  {'Scenario':<38} {'Guardrail':<20} {'Outcome':<20} {'event fired'}")
    print("  " + "-" * 92)
    print(f"  {'Normal run (checkpoint approved)':<38} {'—':<20} {'completed (3/3)':<20} {'RUN_COMPLETED ✓' if ok_happy else 'FAIL'}")
    for name, guardrail, status, event_fired, ok in checks:
        mark = "✓" if (event_fired and ok) else "✗"
        print(f"  {name:<38} {guardrail:<20} {str(status):<20} {mark}")

    n_steps, total_ms, per_step = _plan_metrics()
    ex = Executor(build_registry())  # read the configured ceilings
    print("\n  Per plan (a normal research-to-brief run):")
    print(f"    steps: {n_steps}   ·   total latency: {total_ms} ms   ·   per-step: {per_step} ms")
    print(f"    ceilings — step budget: {ex.max_steps} steps (a plan over it halts: BUDGET_EXCEEDED)   ·   "
          f"retries: {ex.max_attempts} per step, then halt")
    print("    (demo tools are deterministic and near-instant, so latency is orchestration overhead, not tool/model work;")
    print("     in a real deployment 'cost' is the model-call budget that the step budget bounds.)")

    all_ok = ok_happy and all(ev and ok for _, _, _, ev, ok in checks)
    print(f"\nVERDICT: {'PASS — every guardrail fires as designed.' if all_ok else 'FAIL — a guardrail did not fire.'}")


if __name__ == "__main__":
    main()
