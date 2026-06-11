# DEMO.md — Live Demo Script

A tight, repeatable walkthrough. The moments that land hardest: the **plan before
it runs**, a **human checkpoint**, a **guardrail catching a bad step**, and the
**replayable audit trace**. The lead demo is neutral (research-to-brief) on
purpose — the engine is the star, not the domain.

## Before the demo
```bash
make reset      # clear runs, re-init DB, re-register demo tools + sample goals
make run        # uvicorn app.main:app --reload
# open http://localhost:8000
```
Runs cold with no API key: the planner falls back to a deterministic built-in plan
and the tools use a bundled synthetic corpus. Set `ANTHROPIC_API_KEY` in `.env` to
plan with Claude instead (`MODEL_PROVIDER=ollama` for local).

## The ~2-minute happy path

1. **Pose a research question.** The box is pre-filled with a seeded goal
   (*"…benefits and risks of urban green roofs"*). *"This is a general workflow
   engine — point it at any goal. Here it's research-to-brief, on public data."*
   → Proves: framing, generality.

2. **Click "Plan it" — show the plan before anything executes.** Three steps, each
   naming a registered, allowlisted tool, with inputs and expected output; the model
   provider + prompt version are stamped on it. *"It plans first. Nothing runs until
   I can see what it intends to do, and it can only reference allowlisted tools."*
   → Proves: plan-then-execute, controllability.

3. **Click "Plan & run."** Watch `retrieve_documents → summarize_sources` execute,
   each output schema-validated, with per-step timings. The run then **pauses**.
   → Proves: guarded, stepwise execution.

4. **Hit the human checkpoint.** The run halts at `write_brief` (flagged
   consequential) with **Approve / Reject** controls. Click **Approve & continue**.
   *"Consequential steps pause for a human — it resumes only on approval, and the
   decision is recorded."* The cited brief appears.
   → Proves: human-in-the-loop. (Try **Reject** once: the run halts, recorded.)

5. **(The one that lands) Trip a guardrail.** New goal, off-corpus:
   *"Write a brief on quantum teleportation hardware."* Click **Plan & run**.
   Retrieval returns nothing, and the empty result is **caught by the next step's
   input schema** — the run halts with a `validation_failure` event instead of
   summarizing nothing. *"When something goes outside policy, it halts and surfaces
   the event instead of barreling ahead."*
   → Proves: deterministic guardrails around the LLM.

6. **Open the audit log.** Top of the page → **Browse the audit log**, or `/runs`.
   Open any run: the plan, every step with expandable **inputs/outputs**, the
   checkpoint decision, the event trace with relative timings, and the brief. The
   `trace.json` link is the machine-replayable artifact. *"Every plan, tool call,
   and decision is a replayable trace — the difference between a demo and something
   you could operate."*
   → Proves: auditability — the production-mindset signal.

## The credential tie (say once, don't demo it)
*"The same registry → planner → guarded execution → checkpoint → audit pattern is
what powers an internal workflow tool I built and shipped"* — then move on. Keep the
demo on research-to-brief; the internal tool is credited under Experience.

## Transfer targets to mention
Onboarding/provisioning automation, data reconciliation, report generation, research
agents — and healthcare/payer workflows as one of several. *"Swap the tools and
data; the engine doesn't change."*

## Anticipated questions (answers in DECISIONS.md)
- *Why not a single ReAct loop?* → 002 (auditable, checkpoint-able, controllable).
- *How do you stop runaway agents?* → allowlist (003) + budgets/validation (004, 013).
- *What about irreversible actions?* → human checkpoints (005, 014, 015).
- *Could this run without external calls?* → deterministic planner + local corpus
  (010, 011); Ollama for local inference (007).
- *How would this scale to production?* → README path-to-production.

## If something breaks
- Don't debug live. *"Let me reset to a clean state"* → `make reset` → reload.
- Keep a screenshot/recording of the happy path and a saved `trace.json` as a fallback.

## Quick CLI alternative (no browser)
```bash
python -m app.cli "Write a short research brief on urban green roofs."
```
Plans, runs end-to-end (auto-approving the checkpoint), and prints the trace + brief.
