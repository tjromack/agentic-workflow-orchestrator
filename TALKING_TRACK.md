# Talking Track — Agentic Workflow Orchestrator

> Your study reference for speaking on this project. Stage in the portfolio arc: **AUTOMATE** (run
> multi-step AI workflows safely). The defining contrast: this is *not* a single agent loop.

## ⚡ At a glance

- **Pitch:** Runs multi-step AI workflows safely — plans first, executes one guarded step at a time,
  pauses for human approval on consequential actions, and audits everything replayably.
- **Architecture:** A planner emits a typed plan validated against a tool allowlist; the executor runs
  stepwise with guardrails (`$ref` wiring, step budget, schema validation); checkpoints gate; `trace.json` replays.
- **Signature decision:** A plan is a first-class artifact produced *before* any step runs — that's
  what makes it auditable, gatable, and replayable (vs. a black-box ReAct loop).
- **Eval story:** Safety is three demonstrable layers — allowlist (`disallowed_tool` halts),
  deterministic guardrails (`validation_failure` halts), human checkpoints; 8 tests incl. full e2e.

---

## The 60-second pitch

**Business framing:**
"This runs multi-step AI workflows safely. It writes an explicit plan *first*, runs it one guarded
step at a time, pauses for human approval before anything consequential, and records every decision
as a replayable audit trail. Most agent demos are one prompt that does everything — impressive once,
impossible to trust. This is the opposite: every step is inspectable, gatable, and replayable."

**Technical framing:**
"Plan-then-execute, not a ReAct loop. The planner emits an explicit typed plan that's validated
against a tool registry — an allowlist where every tool has JSON-schema'd inputs and outputs. The
executor runs stepwise with guardrails: a step budget, retry-on-transient / halt-on-deterministic,
and `$ref` resolution for cross-step data wiring. Steps marked consequential pause on a human
checkpoint. Everything persists to four tables and reconstructs as a replayable `trace.json`."

---

## Architecture (plan → guarded execution → checkpoint → audit)

```
goal ──▶ PLANNER ──▶ explicit plan (typed steps, each names an allowlisted tool)
                          │  validated against the registry
                          ▼
                     EXECUTOR (stepwise): resolve {"$ref":"step1.field"} ─▶ registry.call ─▶ validate output
                          │  guardrails: step budget · retry-or-halt · schema validation
                          ▼
                     consequential step? ──▶ HUMAN CHECKPOINT (approve / reject)
                          │
                          ▼
                     AUDIT: every plan, tool call, guardrail event, human decision ─▶ trace.json (replayable)
```

- `app/registry.py` — **the allowlist and the only guarded call path.** The planner sees only tool
  *specs* (names + schemas), never the handlers. Safety boundary = registration itself.
- `app/planner.py` — goal → ordered `PlanStep`s (index, tool, inputs, expected_output, consequential);
  LLM-driven with a deterministic fallback when there's no API key.
- `app/executor.py` — guardrails + `$ref` cross-step resolution.
- `app/checkpoints.py` — pause (`awaiting_checkpoint`) / resume / reject; records a `human_decision` event.
- `app/audit.py` — read-only projection over the persisted tables → the trace.
- `app/tools/` — the swap layer: `retrieve`, `summarize`, `write_brief` (each a `dict → dict` handler).
- Tables: `runs`, `plans`, `steps`, `events`.

---

## The eval story (how you prove it's safe)

Safety is **three layers**, and each is demonstrable:

1. **Allowlist** — a plan that names an unregistered tool **halts with a `disallowed_tool` event**;
   it never runs.
2. **Deterministic guardrails** — step budget (no infinite loops), retry-on-transient /
   halt-on-deterministic, and schema validation (a bad output **halts with a `validation_failure`
   event**, not retried).
3. **Human checkpoints** — consequential steps can't proceed without explicit approval.

8 test files, including a **full end-to-end demo test**. The proof artifact is the replayable
`trace.json`: re-run the plan with the same inputs and you get the same outputs.

---

## The signature decision

**A plan is a first-class artifact produced *before* any step runs.** (DECISIONS 002.) That's what
makes the system auditable, gatable, and controllable — you can validate tools, gate consequential
actions, and replay the whole run. A single-shot ReAct loop gives you none of that; it's a black box
you hope behaves.

---

## Honest weakness (say it before they do)

- **Sequential by design** — auditability is prioritized over throughput. Parallel steps, RBAC
  approvals, durable/resumable long-running workflows, and tool sandboxing are explicit
  Path-to-Production items, not shipped.

---

## Other things worth mentioning

- **Domain-agnostic engine:** the shipped demo (research-to-brief) is neutral; swap the tools and
  data and the same engine drives onboarding, reconciliation, provisioning, etc.
- **`$ref` wiring:** steps reference prior outputs with `{"$ref":"step1.documents"}`, resolved at run
  time — that's how data flows through a plan without the model re-deriving it.
- **Zero-key demo:** with no API key the planner falls back to a deterministic plan and the tools use
  a bundled corpus, so the whole thing runs cold and offline — and the trace honestly records that it
  fell back.

---

## The one-liner to remember

> **"It plans before it acts — and because the plan is explicit, every step is something I can
> validate, gate on a human, and replay."**
