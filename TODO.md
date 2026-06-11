# TODO — Phased Build Plan

Build in phases. **Stop at each approval gate.** Commit at every phase boundary.

---

## Phase 0 — Scaffold
- [x] Repo structure per README; `requirements.txt`, `Makefile`, `.env.example`, `.gitignore`.
- [x] FastAPI boots with a health route; base template renders.
- [x] All docs present (`README`, `CLAUDE.md`, `TODO.md`, `DECISIONS.md`, `DEMO.md`).
- **Gate:** app boots; structure agreed.

## Phase 1 — Tool registry (MCP-style)
- [x] `app/registry.py`: register tools with typed input/output schemas and an allowlist.
- [x] Two or three demo tools using public/synthetic data (e.g., a retrieval/search stub, a
      summarize tool, a write-brief tool).
- [x] `make seed` registers tools + sample goals.
- **Gate:** tools are discoverable and callable only through the registry, with schema validation.

## Phase 2 — Planner
- [x] `app/planner.py`: turn a goal into an explicit, ordered plan (step → tool → inputs →
      expected output), using only registered tools.
- [x] Persist the plan; record model + prompt version.
- **Gate:** a goal produces a sensible, inspectable plan that references only allowlisted tools.

## Phase 3 — Executor with guardrails
- [x] `app/executor.py`: run steps one at a time; validate each output against its schema;
      enforce a step/iteration budget; retry-or-halt on failure.
- [x] Surface guardrail events (budget hit, validation failure, disallowed tool) explicitly.
- **Gate:** a plan executes end to end on seeded tools; a deliberately bad step is caught, not
  silently passed.

## Phase 4 — Human checkpoints
- [x] `app/checkpoints.py`: steps flagged consequential/irreversible pause for approval.
- [x] Pause/resume/reject; the decision is recorded.
- **Gate:** a run halts at a checkpoint and only proceeds on explicit approval.

## Phase 5 — Audit log & run viewer
- [x] `app/audit.py`: persist a replayable trace — plan, each tool call (inputs/outputs),
      guardrail events, human decisions, timings.
- [x] UI: a run viewer that shows the plan, step-by-step execution, checkpoints, and the trace.
- **Gate:** any completed run can be inspected and replayed from the audit log.

## Phase 6 — Lead demo (research-to-brief) & polish
- [x] Wire the demo: question → plan → guarded execution (retrieve → summarize → draft) →
      checkpoint to approve the outline → cited brief.
- [x] Empty/error states; graceful handling of model/tool failures.
- [x] Finalize `DEMO.md`; verify `make reset` → demo path works cold.
- **Gate:** full research-to-brief demo runs start to finish from a clean state.

---

## Out of scope (note in README "Path to Production")
Per-tool permission/cost policy engine, tool sandboxing, durable/resumable long runs, RBAC
approvals, queue-backed parallel execution, observability/metrics.
