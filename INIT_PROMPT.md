# INIT_PROMPT.md — Claude Code Kickoff

Paste this into Claude Code in a repo that already contains `README.md`, `CLAUDE.md`, `TODO.md`,
`DECISIONS.md`, and `DEMO.md`.

---

You are helping me build the **Agentic Workflow Orchestrator**. Before writing any code, read
`README.md`, `CLAUDE.md`, `TODO.md`, and `DECISIONS.md`. `CLAUDE.md` is your operating contract —
follow its guardrails exactly, especially: allowlisted tools only (MCP-style registry with typed
schemas), **plan-then-execute** (an explicit, inspectable plan before any step runs), guard every
step (schema validation + step budget + retry-or-halt), **human checkpoints** for consequential
steps, and **audit everything** as a replayable trace. Synthetic/public data and tools only.

Work through `TODO.md` **one phase at a time**. For each phase:

1. Briefly state your plan and any decision points before starting.
2. Implement only that phase. Keep modules small and single-purpose.
3. Make sure `make run` works and the relevant behavior is demoable on seeded tools/goals.
4. Record any non-trivial choice (registry design, planner/executor split, guardrail policy,
   checkpoint rules) in `DECISIONS.md` with the rejected alternative and the why.
5. Make a single, readable commit summarizing what shipped and why.
6. **Stop and wait for my approval before starting the next phase.**

Key requirements:
- The planner emits an explicit plan (step → registered tool → inputs → expected output) and may
  reference only allowlisted tools; persist the plan and record the model + prompt version.
- The executor runs steps one at a time, validates each output against its schema, enforces a
  step/iteration budget, and retries or halts on failure — surfacing guardrail events explicitly.
- Consequential/irreversible steps pause for human approval (pause/resume/reject), and the
  decision is recorded.
- The audit log persists plan, every tool call (inputs/outputs), guardrail events, and human
  decisions as a replayable trace, viewable in the UI.
- The lead demo is **research-to-brief** (retrieve → summarize → checkpoint to approve outline →
  cited brief) on public/synthetic data. Do **not** rebuild any internal/employer tool here.
- `make reset` returns to a clean, seeded state for repeatable demos.

For Phase 1, propose the two or three demo tools (name, typed input/output schema, data source)
for my approval, then implement Phase 0 (scaffold) and stop at the gate.
