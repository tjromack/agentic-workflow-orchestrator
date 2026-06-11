# DEMO.md — Live Demo Script

A tight, repeatable walkthrough. The moments that land hardest: showing the **plan before it
runs**, a **guardrail catching a bad step**, and a **human checkpoint**. The lead demo is
neutral (research-to-brief) on purpose — the engine is the star, not the domain.

## Before the demo
```bash
make reset      # clear runs, re-register demo tools + sample goals
make run        # start server
# open http://localhost:8000
```

## The ~90-second happy path

1. **Pose a research question.** *"This is a general workflow engine — point it at any goal. Here
   it's a research-to-brief task, on public data."*
   → Proves: framing, generality, that it runs.

2. **Show the plan before anything executes.** *"It plans first — explicit steps, each using only
   a registered, allowlisted tool. Nothing runs until I can see what it intends to do."*
   → Proves: plan-then-execute, controllability.

3. **Run it step by step.** Watch retrieve → summarize → draft, each output schema-validated.
   *"It executes one step at a time, validating each result and staying within a step budget."*
   → Proves: guarded, stepwise execution.

4. **Hit the human checkpoint.** Approve the outline. *"Consequential steps pause for a human —
   it resumes only when I approve."*
   → Proves: human-in-the-loop.

5. **(The one that lands) Trip a guardrail.** Trigger a disallowed tool or an over-budget loop.
   *"And when something goes outside policy, it halts and surfaces the event instead of barreling
   ahead."*
   → Proves: deterministic guardrails around the LLM.

6. **Open the audit log.** *"Every plan, tool call, and decision is a replayable trace. That's the
   difference between a demo and something you could operate."*
   → Proves: auditability — the production-mindset signal.

## The credential tie (say once, don't demo it)
*"The same registry → planner → guarded execution → checkpoint → audit pattern is what powers an
internal workflow tool I built and shipped" — then move on.* Keep the demo on research-to-brief;
the internal tool is credited under Experience and shouldn't be re-staged here.

## Transfer targets to mention
Onboarding/provisioning automation, data reconciliation, report generation, research agents —
and healthcare/payer workflows as one of several. *"Swap the tools and data; the engine doesn't
change."*

## Anticipated questions (answers in DECISIONS.md)
- *Why not a single ReAct loop?* → Decision 002 (auditable, checkpoint-able, controllable).
- *How do you stop runaway agents?* → allowlist (003) + budgets/validation (004).
- *What about irreversible actions?* → human checkpoints (005).
- *Could this run without external calls?* → local planner via Ollama (007).
- *How would this scale to production?* → README path-to-production (policy engine, sandboxing,
  durable runs).

## If something breaks
- Don't debug live. *"Let me reset to a clean state"* → `make reset` → reload.
- Keep a screenshot/recording of the happy path and a saved run trace in `docs/` as a fallback.
