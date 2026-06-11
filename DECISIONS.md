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
