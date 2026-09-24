# Agentic Workflow Orchestrator

> © 2026 Trevor J. Romack — **source-available for review, not open-source** ([LICENSE](LICENSE)). No reuse or
> commercial use without permission. · tjromack@gmail.com

A general-purpose engine for running multi-step AI workflows safely: a **tool registry** feeds
a **planner**, a **stepwise executor** runs the plan under **guardrails**, **human checkpoints**
gate consequential steps, and an **audit log** records everything. Swap the tools and the data,
and the same core drives very different jobs.

> Built and demonstrated on **synthetic and public data only** — no PHI, no internal systems.
> A personal portfolio prototype.

**Demonstrates:** running an agent under enforced guardrails — a step budget, retry-then-halt, a human checkpoint on
consequential steps, schema-validated tool output, and an allow-listed registry — with every guardrail exercised and
published (`make guardrails`, `EVAL.md`).

![Plan & run: the executor runs an inspectable plan step by step and pauses at the consequential step for human approval](docs/agent-orchestrator-demo.gif)

*`Plan & run` on a goal: the planner emits an inspectable three-step plan, the executor runs it one step at a time, and
it **pauses at the consequential `write_brief` step for human approval** — nothing irreversible runs until you approve.
Every step and guardrail decision lands in the audit trace.*

---

## The problem it solves

Most "AI agent" demos are a single prompt that does everything in one shot — impressive once,
impossible to trust, audit, or control. Real workflows need the opposite: an explicit plan, a
fixed set of allowed tools, validation between steps, a human in the loop where it matters, and
a record of what happened. This orchestrator is that reliable middle layer — the part that
turns "an LLM that can call tools" into "a workflow you'd actually put into production."

## Who it's for

Anyone building multi-step automation with an LLM who needs it to be controllable and auditable
rather than a black box.

## What it does (the architecture)

1. **Tool registry (MCP-style)** — tools are registered with typed input/output schemas and an
   allowlist. The planner can only use what's registered; nothing else is reachable.
2. **Planner** — decomposes a goal into an explicit, inspectable sequence of steps (which tool,
   what inputs, expected output) before anything runs.
3. **Stepwise executor with guardrails** — runs one step at a time, validates each output
   against its schema, enforces a step/iteration budget, and retries or halts on failure.
4. **Human checkpoints** — consequential or irreversible steps pause for human approval; the run
   resumes (or is rejected) from there.
5. **Audit log** — every plan, tool call, input/output, guardrail event, and human decision is
   recorded as a replayable trace.

## Lead demo: research-to-brief

The shipped demo is a neutral research agent. Given a question, it plans a short research
workflow, calls retrieval/summarize tools step by step, pauses at a checkpoint for you to
approve its outline, and produces a cited brief — with the full run visible in the audit log.

## Transfers to

The engine is domain-agnostic. The same registry → planner → guarded execution → checkpoints →
audit pattern drives: onboarding and provisioning automation, data reconciliation, report and
document generation, research agents, and — as one of several targets — healthcare/payer
operations workflows. Point it at different tools and data; the core doesn't change.

*The same orchestration pattern powers an internal workflow tool I built and shipped (credited
under Experience). This repo is the generalized, neutral version of that pattern — not that
tool — so the engine can be shown and judged on its own.*

## Tech stack

- **Backend:** FastAPI (Python)
- **Storage:** SQLite (runs, plans, steps, audit log)
- **Frontend:** HTMX + server-rendered templates (run viewer, checkpoint approvals)
- **Planner/agent:** Anthropic Claude by default; pluggable to a local model via Ollama
- **Tools:** an MCP-style registry with typed schemas (demo tools use public/synthetic data)

See `DECISIONS.md` for why each choice was made over the alternatives.

## Quickstart

**macOS / Linux:**
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

make seed        # register demo tools + sample goals
make run         # uvicorn app.main:app --reload  → http://localhost:8000
make guardrails  # exercise every guardrail and print the behaviour table (EVAL.md)
make reset       # clear runs and re-seed for a clean demo
```

**Windows (PowerShell):** no `make`, and PowerShell has no `&&` — call the modules directly:
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

.venv\Scripts\python -m app.seed
.venv\Scripts\python -m uvicorn app.main:app --port 8000     # → http://localhost:8000
.venv\Scripts\python -m app.guardrails                       # the guardrail behaviour table
```

Set `ANTHROPIC_API_KEY` in `.env`, or `MODEL_PROVIDER=ollama` to run the planner locally. Detection of guardrail
behaviour (`make guardrails`) and the test suite run fully offline — no key needed.

## Responsible AI & data

- **Synthetic/public data and tools only** — no PHI, no internal systems.
- **The planner proposes; guardrails and humans dispose.** Tools are allowlisted, steps are
  budgeted and schema-validated, and consequential actions require human approval.
- **Everything is auditable** — each run is a replayable trace, which is the difference between
  a demo and something operable.

## Limits — what this does *not* let you claim

- **It orchestrates control-flow; it does not judge task quality.** The eval proves the agent stops when it should — it
  does not score how good the resulting brief is (that is the evaluation harness's job).
- **The demo tools are deterministic stubs** over public/synthetic data, and the planner runs offline (`provider=None`).
  Real tools and a real planner add their own failure modes — which is what the guardrails exist to contain.
- **`max_steps` / `max_attempts` are configured, not learned** — sensible per-run defaults, not tuned against a workload.
- **Not a multi-agent system.** It is a single planner-executor loop with a human checkpoint, not agents negotiating.
- **Synthetic / public data and tools only** — no PHI, no internal systems.

## Path to production

- **Guardrails:** richer policy engine (per-tool permissions, rate/cost budgets), sandboxing of
  tool execution, and typed failure handling.
- **Reliability:** durable run state, resumable long-running workflows, idempotent tool calls.
- **Governance:** role-based approvals, full audit retention, and per-tool data-handling
  controls (and a BAA / in-boundary model for any sensitive-data tool).
- **Scale:** queue-backed execution, parallel steps where safe, observability/metrics.

## Project structure

```
app/
  main.py          # FastAPI app + routes
  registry.py      # MCP-style tool registry: schemas + allowlist
  planner.py       # goal → inspectable step plan
  executor.py      # stepwise execution, validation, budgets, retries
  checkpoints.py   # human approval gates (pause/resume)
  audit.py         # replayable run trace
  guardrails.py    # exercise every guardrail + print the behaviour table (EVAL.md)
  tools/           # demo tools (public/synthetic data)
  templates/       # run viewer + checkpoint approvals
data/
  demo_goals.seed.json
tests/conftest.py  # every test gets an isolated, initialized DB (fresh `pytest` needs no `make seed`)
DECISIONS.md  DEMO.md  EVAL.md  TODO.md  CLAUDE.md
```

## Status

All phases shipped (0–6): tool registry, planner, guarded executor, human checkpoints, audit log + run viewer, and the
research-to-brief demo. Guardrail behaviour is exercised and published — `make guardrails`, **7/7 fire as designed**
(`EVAL.md`). The full demo runs cold from `make reset`; a fresh `pytest` passes without a seed. See `DEMO.md` for the
walkthrough and `TODO.md` for the phased plan.
