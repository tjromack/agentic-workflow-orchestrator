# CLAUDE.md — Operating Contract

Working agreement for building this project with Claude Code. Read it before each session.

## Purpose

Build the **Agentic Workflow Orchestrator**: a FastAPI engine that plans and runs multi-step
LLM workflows under guardrails, with human checkpoints and a full audit log. The lead demo is a
neutral **research-to-brief** agent. This is an interview-demo prototype that must run reliably
and be fully auditable.

## Operating principles (guardrails)

1. **Allowlisted tools only.** The planner and executor may only use tools registered in the
   MCP-style registry, each with typed input/output schemas. No ad-hoc or unregistered calls.
2. **Plan, then execute.** Always produce an explicit, inspectable plan before running steps.
   The plan is a first-class object, not an internal afterthought.
3. **Guard every step.** Validate each tool output against its schema; enforce a step/iteration
   budget; retry or halt on failure. Never loop unbounded.
4. **Humans gate consequential steps.** Any step marked consequential or irreversible pauses for
   human approval and resumes only on explicit approval.
5. **Audit everything.** Persist every plan, tool call (inputs/outputs), guardrail event, and
   human decision as a replayable trace.
6. **Synthetic/public data and tools only.** No PHI, no internal systems. Record the model +
   prompt version on each plan.
7. **Neutral demo.** The lead demo is research-to-brief. Do not rebuild any internal/employer
   tool here.

## Stack

- Python 3.11+, FastAPI, Uvicorn
- SQLite via `sqlite3` (runs, plans, steps, audit)
- HTMX + Jinja2 templates
- Anthropic SDK for planning; provider abstraction so `MODEL_PROVIDER=ollama` runs locally
- MCP-style tool registry with typed schemas; `pytest` for tests

## Commands

```bash
make install   # venv + install
make seed      # register demo tools + sample goals
make run       # uvicorn app.main:app --reload
make test      # pytest
make reset     # clear runs + re-seed (clean demo state)
make fmt       # format
```

## Conventions

- Small, single-purpose modules (see README structure).
- Tools declare typed input/output schemas; the executor enforces them.
- Each run persists its plan, every step, and the audit trace.
- No secrets in code; read from `.env`.
- **Commit at each phase boundary** with a readable message; the git history is an interview
  artifact.
- Update `DECISIONS.md` on every non-trivial choice (registry design, planner/executor split,
  guardrail policy, checkpoint rules) with the rejected alternative and the why.

## Definition of done (per phase)

- The phase's checklist in `TODO.md` is complete.
- `make run` works and the relevant behavior is demoable on seeded tools/goals.
- New decisions recorded; a commit marks the phase boundary.
- **Stop and wait for my approval before the next phase.**

## Do not

- Do not let the planner call tools outside the registry/allowlist.
- Do not execute consequential/irreversible steps without a human checkpoint.
- Do not run steps unbounded — always enforce the budget.
- Do not use real/PHI data or rebuild internal tooling; do not pass an approval gate without approval.
