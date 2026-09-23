# EVAL.md — does the agent stay inside its guardrails?

An orchestrator that runs tools on a user's behalf is only as trustworthy as the limits it will not cross. This project's
eval is therefore about **control-flow safety**, not answer quality: given a plan, does each guardrail fire when it
should, and does the run halt rather than barrel on? Every check here is deterministic — no model call — because the
guardrails are deterministic by design.

Run with `make guardrails` (`python -m app.guardrails`). The guardrail behaviour is also asserted case-by-case in
`tests/test_executor.py`.

---

## The guardrails, and why each exists

| Guardrail | What it does | Why it matters |
|---|---|---|
| **Step budget** | refuses a plan (or an iteration loop) beyond `max_steps` | an agent that can plan its own steps can loop forever; the budget bounds it |
| **Retry-then-halt** | retries a transient tool error up to `max_attempts`, then halts | tolerate a blip, but never mask a tool that is actually broken |
| **Human checkpoint** | a `consequential` step pauses (`AWAITING_CHECKPOINT`) until approved | the human decides before an irreversible action runs, not after |
| **Schema validation** | every tool output is validated against its declared output schema | a tool returning the wrong shape halts the run instead of poisoning the next step |
| **Allow-listed tools** | a step naming an unregistered tool is refused | the agent can only call tools it was explicitly given |

## Output

Real output of `make guardrails` — every guardrail exercised on a constructed plan:

```
Guardrail behaviour — the orchestrator's safety story, exercised

  Scenario                               Guardrail            Outcome              event fired
  --------------------------------------------------------------------------------------------
  Normal run (checkpoint approved)       —                    completed (3/3)      RUN_COMPLETED ✓
  Consequential step, no approval        human checkpoint     awaiting_checkpoint  ✓
  Consequential step, rejected           human checkpoint     halted               ✓
  Plan over the step budget (5 > 3)      step budget          halted               ✓
  Tool fails every attempt (retry x2)    retry-then-halt      failed               ✓
  Tool output violates its schema        schema validation    failed               ✓
  Plan calls an unregistered tool        allow-listed tools   failed               ✓

  Every step is timed in the audit trace: 3/3 steps carry a recorded duration_ms on a persisted run

VERDICT: PASS — every guardrail fires as designed.
```

Every step and every guardrail decision is written to an append-only audit trail (`app/audit.py`), so a completed or
halted run can be reconstructed after the fact — the trace carries per-step `duration_ms` and a run `total_ms`.

## Limits

- **This measures control-flow, not task quality.** It proves the agent stops when it should; it does not score how good
  the resulting brief is. Output quality is the target-system's concern, evaluated by the LLM Evaluation & Guardrails
  Harness, not here.
- **The tools are deterministic stubs.** Timing reflects orchestration overhead, not real tool or model latency, and the
  planner runs offline in the demo (`provider=None`). Real tools and a real planner would add their own failure modes —
  which is exactly what the guardrails exist to contain.
- **`max_steps` / `max_attempts` are configured, not learned.** They are sensible defaults, set per run, not tuned
  against a workload.
