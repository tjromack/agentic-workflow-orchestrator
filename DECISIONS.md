# DECISIONS.md — Decision Log

Lightweight ADRs. One entry per non-trivial choice: the decision, the alternative, the why.
These are the script for "why did you build it this way?" Add an entry on every real tradeoff.

**Template**
```
## NNN. <Decision title>
- Date / phase:
- Decision:
- Alternatives considered:
- Why:
- Tradeoff accepted:
- Revisit if:
```

---

## 001. Stack: FastAPI + SQLite + HTMX
- Phase: 0
- Decision: Server-rendered HTMX on FastAPI with file-based SQLite.
- Alternatives considered: React SPA + API; a heavier agent framework with its own UI.
- Why: One developer, must demo reliably and reset in one command. SQLite stores runs/plans/audit
  and resets instantly; HTMX gives a real run viewer and approval UI without a build step.
- Revisit if: Concurrency or a richer UI is needed → Postgres + a JS framework.

## 002. Plan-then-execute, not single-shot agent
- Phase: 2
- Decision: The planner emits an explicit, inspectable plan; a separate executor runs it.
- Alternatives considered: A single ReAct-style loop where the model decides and acts in one
  stream.
- Why: An explicit plan is what makes the system auditable, checkpoint-able, and controllable. You
  can show the plan before anything runs, gate it, and replay it. A single-shot loop is a black
  box that's hard to trust or stop.
- Tradeoff accepted: Slightly less flexible than free-form looping; that rigidity is the point.
- Revisit if: A use case genuinely needs dynamic replanning → add bounded replanning between steps.

## 003. MCP-style tool registry with an allowlist
- Phase: 1
- Decision: Tools are registered with typed schemas; the planner/executor can only use what's
  registered.
- Alternatives considered: Letting the model call arbitrary functions or shell out.
- Why: The allowlist is the primary safety boundary — the agent literally cannot reach a tool it
  wasn't granted. Typed schemas let the executor validate every input/output.
- Tradeoff accepted: Every capability must be explicitly registered; worth it for control.

## 004. Deterministic guardrails around a non-deterministic planner
- Phase: 3
- Decision: Schema validation between steps, a step/iteration budget, and retry-or-halt — all
  deterministic — wrap the LLM planning step.
- Why: The model is the creative, fallible part; the guardrails are the predictable cage around
  it. Budgets prevent runaway loops; validation prevents a bad step from cascading.
- Tradeoff accepted: A valid run can occasionally be halted by a strict guardrail; tunable.

## 005. Human checkpoints for consequential/irreversible steps
- Phase: 4
- Decision: Steps flagged consequential pause for human approval before running.
- Alternatives considered: Fully autonomous execution.
- Why: For anything with real-world effect, a human should approve before it happens. This is the
  responsible default and the pattern real deployments need.
- Tradeoff accepted: Not fully hands-off; that's intended for consequential work.

## 006. Audit log as a first-class, replayable artifact
- Phase: 5
- Decision: Persist plan, every tool call (inputs/outputs), guardrail events, and human decisions.
- Why: Auditability is what separates a demo from something operable. It's also the debugging and
  trust mechanism — you can always answer "what did it do and why?"

## 013. Retry-or-halt policy: retry transient errors, halt deterministic ones
- Phase: 3
- Decision: The executor retries a step (up to `max_attempts`) only on a generic
  tool runtime error. A `SchemaValidationError` or a `ToolNotAllowed` halts the run
  immediately — no retry. A step budget (`max_steps`) caps both plan length and
  iterations. Every decision emits an explicit event.
- Alternatives considered: Retry everything uniformly; never retry; retry with
  backoff/jitter.
- Why: Retrying a deterministic failure (bad schema, disallowed tool) just burns the
  budget and produces the same error — those are bugs to surface, not transients to
  paper over. Retry is reserved for the failures that are plausibly transient (a flaky
  tool/model call). Halting loudly is the safe default for a guarded engine.
- Tradeoff accepted: A genuinely transient validation blip won't be retried; acceptable
  because tool outputs here are deterministic. Revisit if tools become nondeterministic.

## 014. Checkpoints are a pause-by-default seam driven by an approvals map
- Phase: 3 (made interactive in Phase 4)
- Decision: A consequential step pauses the run (`awaiting_checkpoint`) and returns
  unless an explicit approval for that step index is supplied. Approvals are a simple
  `{step_index: bool}` map the executor already honors; Phase 4 just populates it from
  the UI and resumes from persisted state. Run state (steps + events) persists to
  SQLite so a paused run is resumable. The CLI auto-approves to demonstrate full
  end-to-end execution.
- Alternatives considered: Run consequential steps and undo on rejection; a callback
  interface; auto-approve in the web app for the Phase 3 gate.
- Why: Pausing *before* the effect honors the contract ("never run consequential steps
  without approval") with no compensating logic, and the approvals-map seam means the
  interactive gate in Phase 4 is additive, not a rewrite. Persisting steps/events now
  doubles as the audit-trace backbone the Phase 5 viewer renders.
- Tradeoff accepted: "End to end" in the web app means *up to the checkpoint* by
  default; the full chain is shown via the CLI/tests that pass approvals.

## 015. Resume by carrying persisted outputs forward; decision is an audit event
- Phase: 4
- Decision: Resuming a paused run reconstructs the plan + already-succeeded step
  outputs from SQLite and re-invokes the executor with `prior_outputs` (carried,
  not re-run) plus an approval for the pending step. The human decision is written
  to the same `events` trace (`human_decision`) before execution resumes; rejection
  halts the run with the step marked `rejected`. The run trace is always rendered
  from persisted state, so `/run` and `/resume` show one complete picture.
- Alternatives considered: Re-run the whole plan on resume; keep the paused run in
  memory; run the consequential step and compensate on rejection; a separate
  decisions table.
- Why: Carrying outputs forward makes resume cheap and idempotent and means a paused
  run survives a restart (state is in the DB, not memory). Recording the decision in
  the existing event trace keeps the audit single-sourced and replayable. Rendering
  from persisted state is the same read path the Phase 5 viewer will use.
- Tradeoff accepted: Resume trusts persisted outputs rather than recomputing them;
  fine for deterministic tools, and the schema still re-validates anything re-run.
- Revisit if: Tools become nondeterministic or outputs expire and must be recomputed.

## 016. Audit is a read-only projection over the persisted tables
- Phase: 5
- Decision: `app/audit.get_trace` assembles the full trace (plan + per-step resolved
  inputs/outputs + events + human decisions + timings) by joining the existing runs,
  plans, steps, and events tables — it persists nothing new. The same trace backs the
  HTML viewer (`/runs`, `/runs/{id}`) and a `trace.json` artifact. Step durations come
  from a `running` row stamped at step start plus the completion update.
- Alternatives considered: A denormalized audit table written alongside execution; an
  event-sourcing log as the sole source of truth.
- Why: The execution path already persists everything needed (Phases 2–4), so a derived
  read-model avoids dual writes that could drift from what actually ran. "Replayable"
  here means the trace is fully reconstructable from persisted state — which `trace.json`
  makes explicit. One assembly function means the live partial and the after-the-fact
  viewer never disagree.
- Tradeoff accepted: Assembling the trace on each view is recomputed rather than cached;
  trivial at demo scale. Revisit with run volume → materialize or paginate.

## 017. Stopword-filtered retrieval; empty results are a guardrail, not a fallback
- Phase: 6
- Decision: `retrieve_documents` filters function/instruction words ("write a brief
  on…") before matching, scoring documents by the fraction of *content* query terms
  they cover. An off-corpus query therefore returns zero documents, and the empty
  result is caught by the next step's input schema (which requires ≥1 document) —
  the run halts with a `validation_failure` rather than summarizing nothing.
- Alternatives considered: Keep naive token overlap (matched on "a"/"on"/"the", so
  every query "found" sources); have retrieve fabricate a placeholder on no match;
  special-case empty results in the executor.
- Why: Naive overlap made retrieval meaningless and made it impossible to demo a
  guardrail trip. Letting the schema boundary catch the empty hand-off keeps the
  failure in the deterministic guardrail layer (Decision 004) instead of adding
  bespoke logic — the engine's own validation is the safety net, which is the point.
- Tradeoff accepted: The stopword list is hand-maintained and English-only; fine for
  a synthetic-corpus demo. Revisit with real retrieval (embeddings/BM25).

## 011. Provider abstraction with a deterministic planner fallback
- Phase: 2
- Decision: A tiny `Provider` interface (`complete(system, user) -> str`) backs the
  planner; `make_provider` returns Anthropic, Ollama, or `None`. With no provider
  (no API key) — or if the provider call fails — the planner emits a deterministic
  built-in plan. The plan records the actual `model_provider` / `model_name` used,
  including a "(fallback: …)" note when it fell back.
- Alternatives considered: Require an API key; hard-code Anthropic; fail closed when
  the model is unavailable.
- Why: The demo must run cold and offline (Decision 010) yet still show real LLM
  planning when a key is present. Fallback keeps the demo resilient; recording the
  true provider/model keeps the audit honest.
- Tradeoff accepted: A silent fallback could mask a misconfigured key; mitigated by
  surfacing the fallback reason in the recorded model name.
- Revisit if: We want planning failures to halt loudly rather than degrade.

## 012. The plan is a first-class persisted object; allowlist enforced post-hoc
- Phase: 2
- Decision: `Plan`/`PlanStep` are explicit dataclasses persisted to SQLite (runs +
  plans tables) with model + prompt version. After any planner produces steps, every
  referenced tool is validated against the registry and each step's `consequential`
  flag is overwritten from the registry (the registry, not the model, is
  authoritative). Cross-step data flow uses `{"$ref": "stepN.field"}` references.
- Alternatives considered: Keep the plan as transient model output; trust the model's
  own tool list and flags; persist plans as loose JSON files.
- Why: An inspectable, persisted plan is what makes the system auditable and
  checkpoint-able (Decision 002). Validating tools post-hoc means even an LLM that
  hallucinates a tool cannot get a disallowed step into a plan. SQLite is the
  documented store and resets cleanly for demos.
- Tradeoff accepted: A separate validation pass and a ref-resolution convention the
  executor must honor (Phase 3); worth it for the allowlist guarantee.
- Revisit if: Plans need richer control flow (branches/loops) than a linear ref DAG.

## 009. JSON Schema (Draft 2020-12) validated in the registry's call path
- Phase: 1
- Decision: Tools declare plain JSON Schema for input and output; `registry.call`
  is the single entry point and validates both sides on every call. Schemas are
  checked for validity at registration time, not first use.
- Alternatives considered: Pydantic models per tool; validating only in the
  executor (Phase 3).
- Why: JSON Schema is the MCP-aligned, language-agnostic contract — the *same*
  object validates a call and is handed to the planner (`registry.specs()`) as the
  description of what the tool accepts. Validating in the registry makes the call
  path itself the enforcement boundary, so nothing can call a tool incorrectly even
  outside the executor. The executor (Phase 3) layers budgets/retries on top.
- Tradeoff accepted: Less ergonomic than Pydantic for Python authors; worth it for
  a serializable, planner-visible, transport-neutral contract.
- Revisit if: We need richer cross-field validation than JSON Schema expresses.

## 010. Deterministic local corpus + deterministic tool stubs
- Phase: 1
- Decision: `retrieve_documents` searches a bundled synthetic corpus
  (`data/corpus/documents.json`); `summarize_sources` and `write_brief` ship as
  deterministic implementations that run with no API key. The schema is the
  contract, so an LLM-backed handler can replace either later without changing
  callers.
- Alternatives considered: Live web search; requiring an API key for the demo.
- Why: Repeatable, offline, cold-start demos — `make reset` always reproduces the
  same run — and it honors "synthetic/public data only." Decouples the registry
  gate from model availability.
- Tradeoff accepted: Stub summaries are mechanical, not "smart," until the LLM path
  lands (Phase 2 provider abstraction).
- Revisit if: The demo needs genuinely model-written summaries by default.

## 007. Synthetic/public data + local-model option
- Phase: 1/2
- Decision: Demo tools use public/synthetic data; the planner can run on a local model via Ollama.
- Why: Governance and honesty (no real/internal data), plus a privacy-preserving inference path
  for sensitive environments.

## 008. Neutral lead demo (research-to-brief), decoupled from internal work
- Phase: 6
- Decision: The headline demo is a general research agent, not a re-creation of any internal tool.
- Why: The engine should be judged on its own, in a neutral domain, to show the pattern
  generalizes. The real internal tool that uses this pattern is credited under Experience and
  speaks for itself; re-staging it here would read as a clone and muddy the "transferable engine"
  story.

## 018. Retrieval has a relevance floor (not just a term-overlap rank)
- Decision: `retrieve_documents` excludes any document scoring below a **relevance floor**
  (`MIN_RELEVANCE = 0.5` of the query's content terms; a plan may override via `min_score`). Previously it
  ranked by term-overlap and returned the top-k of anything sharing ≥1 term.
- Why: Ranking without a floor let a k larger than the number of *relevant* documents pull noise into a
  brief. On 2026-07-18 a `k=8` "urban green roofs" query returned a **community-solar** section — it matched
  only the shared word "urban" (score 0.33). A floor makes irrelevant documents *absent* rather than merely
  low-ranked, so an off-topic or thin query returns fewer — or zero — documents. This mirrors, in spirit, the
  RAG copilot's abstention threshold: below the floor, a "match" is noise. The planner can still widen recall
  deliberately by passing a lower `min_score`.
- Rejected: Raising/lowering k per query (k is a count, not a relevance control — the floor is the right
  knob); a global constant with no override (a plan sometimes *wants* broad recall); re-ranking without
  filtering (the bug was inclusion, not order). Regression test reproduces the green-roofs/solar case.

## 019. Step duration is execution-only; human-checkpoint wait is reported separately
- Decision: A step's `duration_ms` is measured from its **STEP_STARTED** event (which fires *after* a
  consequential step's checkpoint is approved) to its end — so it is execution time only. The pause a step
  spent awaiting human approval is reported as a separate **`waiting_ms`** (from the step's `created_at`,
  stamped when it first paused, to STEP_STARTED; clamped to ≥0 for non-paused steps). The viewer shows
  "N ms exec" and, when there was a pause, "waited N ms for approval".
- Why: The previous `duration_ms` ran from `created_at` to `updated_at`; for a consequential step,
  `created_at` is stamped when it *pauses* for approval, so the duration swallowed the human-think time —
  once **199,556 ms** vs ~5 ms for the auto steps (2026-07-18). Any cost/latency metric built on that would
  be badly misleading. Deriving execution start from STEP_STARTED (post-approval) is a pure read-side fix —
  no schema migration, and it splits the two genuinely different quantities: how long the *tool* took vs how
  long the *human* took.
- Rejected: Adding a `started_at` column (a schema migration for what the events already record); leaving one
  blended number (conflates machine time and human time — the whole complaint); subtracting a fixed fudge
  (the wait is variable). The event log was already the source of truth for *when* execution began.

## 020. A dead-branch plan is overridable in the UI ("plan anyway"), not a dead-end
- Decision: `_validate_no_dead_branches` raises a distinguishable **`DeadBranchError`** (subclass of
  `PlannerError`). The web `/plan` and `/run` routes accept an `allow_dead_branches` form flag and, on a
  `DeadBranchError`, render an error card with a **"Plan anyway" / "Run anyway"** button that re-submits the
  same goal with `allow_dead_branches=true`. Other `PlannerError`s (e.g. a disallowed tool) offer no override.
- Why: Plan-graph validation rightly rejects an orphaned-step plan — but only the *live* LLM planner ever
  produces one (the deterministic fallback is always coherent), so before this the web demo could hit a
  reject with no way forward. A dead branch is a *warning* (the orphaned step runs and is discarded), not a
  safety violation, so the right UX is a deliberate, one-click override — the override already existed as
  `build_plan(allow_dead_branches=True)`; this wires it to the UI. A disallowed-tool error is *not*
  overridable, so only `DeadBranchError` gets the button.
- Rejected: Auto-allowing dead branches (removes a useful signal — the planner produced waste); silently
  dropping orphaned steps (changes the plan behind the user's back); one generic error with no path forward
  (the original dead-end). Overriding stays a conscious click, and the trace still records it ran with the override.

## 021. An invalid LLM plan (type-mismatched refs) falls back to deterministic; a disallowed tool does not
- Decision: In `build_plan`, when a provider is configured, the LLM's plan is structurally validated *before* it is
  returned. A **type-mismatched reference** (e.g. wiring `step1.documents` — an array — into an input that expects a
  string) means the model wired otherwise-valid tools together incorrectly; `build_plan` **falls back to the
  deterministic plan** and stamps `model_name` with `(fallback: PlannerError)` so the substitution is visible in the
  plan/trace. A **disallowed / unregistered tool** is treated differently: it is **rejected** (`_validate_against_registry`
  raises, uncaught), never swapped for a safe plan.
- Why: A reviewer posing a free-form goal with a real key would otherwise hit a raw "this plan would fail at run time"
  error when the model mis-wired a reference — a poor first impression for a demo whose story is the guardrails, not the
  planner's wiring. The tools are all allowlisted and the deterministic plan is always coherent, so recovering to it is
  safe and keeps the demo working on any goal. A disallowed tool is the opposite case: the model reaching for a tool it
  was not given is exactly the attempt the allow-list exists to surface, so it stays a loud rejection.
- Rejected: Falling back on *every* validation failure (would hide a disallowed-tool attempt — a security signal);
  surfacing the raw ref error to the user (the pre-fix behaviour — a dead-end for a casual reviewer); silently swapping
  without recording it (changes the plan behind the user's back — the `(fallback: …)` stamp keeps it honest).
