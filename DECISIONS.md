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
