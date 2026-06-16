# MASTERY.md — Owning This Project

Five things to do without notes: **explain** it in 60 seconds, **draw** the architecture
from a blank board, **rebuild** the core engine cold, **extend** it to a new domain by
swapping one layer, and **defend** every design decision to a skeptic.

> **Quick map of the codebase**
> - `app/registry.py` — MCP-style tool registry: the allowlist *and* the only guarded call path (schema-validates in and out).
> - `app/planner.py` — goal → explicit, persisted, allowlist-only `Plan` of steps.
> - `app/providers.py` — Anthropic / Ollama / deterministic-fallback behind one `complete()` interface.
> - `app/executor.py` — stepwise execution under guardrails: budget, retry-or-halt, `$ref` resolution, consequential pause.
> - `app/checkpoints.py` — pause / approve / reject / resume from persisted state.
> - `app/audit.py` — read-only projection that assembles the replayable trace.
> - `app/store.py` — SQLite: `runs`, `plans`, `steps`, `events`.
> - `app/tools/` — **the swap layer**: `retrieve_documents`, `summarize_sources`, `write_brief`.
> - `app/main.py` — FastAPI routes (`/plan`, `/run`, `/resume`, `/runs`, `/runs/{id}`, `trace.json`).
> - `app/config.py`, `app/paths.py`, `app/seed.py`, `app/cli.py` — settings, paths, seed, headless runner.

---

## 1. Explain what it does and why, in plain English, in 60 seconds

> It's a workflow engine that runs multi-step LLM tasks the way you'd actually put one into
> production — not a single prompt that does everything in one shot. You give it a goal; it
> first writes an explicit **plan** — which registered tool, what inputs, what output — and
> nothing runs until you can see that plan. Then it executes one step at a time, validating
> every input and output against a JSON schema, enforcing a step budget, and retrying or
> halting on failure. Anything marked **consequential** pauses for a human to approve or
> reject before it runs. And every plan, tool call, guardrail event, and human decision is
> persisted as a **replayable audit trace**. The shipped demo is neutral — research-to-brief
> on synthetic data — but the engine is domain-blind: swap the tools and data and the same
> plan-guard-gate-audit core drives a completely different job.

**The one-sentence version:** a guarded, auditable orchestrator that plans before it acts,
validates every step, gates consequential actions on a human, and records everything.

**The three words to never lose:** **plan-then-execute**, **allowlist**, **audit**.

**Self-check:** you've got it when you can say the anchor property — *the planner proposes;
deterministic guardrails and humans dispose* — without reaching for the word "agent."

---

## 2. Draw the architecture from memory

```
   goal
    │
    ▼
 ┌───────────┐   specs (names+schemas,   ┌────────────────┐
 │  planner  │◀──  never handlers)  ─────│   registry     │  allowlist + JSON schemas
 └─────┬─────┘                           └───────┬────────┘  call(): valid-in→run→valid-out
       │ Plan: steps, tool, inputs,              │
       │ $ref wiring, consequential              │ (the one external model call is here:
       ▼                                         │  planner→providers, else deterministic)
 ┌───────────┐   one step at a time     ┌────────▼────────┐
 │ executor  │─────────────────────────▶│  tools/ (SWAP)  │ retrieve→summarize→write_brief
 └─────┬─────┘  budget · retry-or-halt  └─────────────────┘
       │  ▲     · $ref resolve
       │  │ pause @ consequential step
       ▼  │ approve / reject
 ┌───────────┐   writes every event,    ┌─────────────────┐
 │checkpoints│   step, decision ───────▶│  store (SQLite) │ runs·plans·steps·events
 └─────┬─────┘                          └────────┬────────┘
       │                                         │ reads (no new writes)
       ▼                                         ▼
 ┌───────────┐                          ┌─────────────────┐
 │   audit   │  read-only projection ──▶│ /runs, /runs/id │  + trace.json (replay artifact)
 └───────────┘                          └─────────────────┘
```

**Memory aids:**
- **Ordered stages (mnemonic "Real Plans Execute Clean Audits"):** **R**egistry → **P**lanner →
  **E**xecutor → **C**heckpoints → **A**udit.
- **Offline / online split:** everything is **offline and deterministic** by default — the local
  synthetic corpus, the tools (deterministic stubs), and the planner's built-in fallback. The
  **only** external network call is the planner asking a provider for a plan, and *only* when
  `MODEL_PROVIDER`/`ANTHROPIC_API_KEY` (or Ollama) is configured. No key → deterministic plan,
  full demo still runs.
- **Where the model call happens:** `planner._llm_steps()` via `providers.Provider.complete()`.
  The tools themselves make **no** model calls in this build.

**Self-check:** you can redraw it when you can place all four SQLite tables (`runs`, `plans`,
`steps`, `events`) and say which arrow is the lone external call.

---

## 3. Rebuild this core engine from scratch

**Build order & contracts** (this is also the actual git history, Phase 0→6):

1. **`registry.py` — the allowlist + guarded call path.** Contract: `register(Tool)` adds a
   tool keyed by name (registration *is* the allowlist); `call(name, inputs) -> outputs`
   enforces, in order, allowlist membership → input schema → run handler → output schema.
   `specs()` exposes names+schemas **without handlers** for the planner. It's first because
   it's the safety boundary everything else routes through.
2. **`planner.py` — goal → Plan.** Contract: `build_plan(goal, registry, provider) -> Plan`
   where `Plan` is an ordered list of `PlanStep(index, tool, inputs, expected_output,
   consequential)`. Every `step.tool` is validated against the registry and `consequential`
   is copied **from the registry, not the model**. With no provider it emits the deterministic
   plan; `PROMPT_VERSION = "planner/v1"` is recorded. Comes after the registry because a plan
   may only reference allowlisted tools.
3. **`store.py` — persistence.** Contract: `create_run`, `save_plan`, `record_step` (upsert
   keyed `{run_id}:{index}`), `record_event`, `set_run_status`, plus getters; `init_db` /
   `reset_db`. Four tables: `runs`, `plans`, `steps`, `events`. The plan must be persisted with
   model + prompt version before execution.
4. **`executor.py` — guarded stepwise execution.** Contract:
   `Executor(registry, max_steps=10, max_attempts=2).run(run_id, plan, approvals, prior_outputs)
   -> RunResult`. Resolves `{"$ref": "stepN.field"}` inputs from prior outputs, calls each tool
   through `registry.call` (so schemas re-validate), enforces the step budget, retries transient
   tool errors but **halts immediately** on a validation failure or disallowed tool, and **pauses**
   at a consequential step unless approved. Emits an explicit event for every decision.
5. **`checkpoints.py` — human gate + resume.** Contract: `resume(registry, run_id, decision)`
   reconstructs the plan and succeeded-step outputs from SQLite, records a `human_decision`
   event, then re-invokes the executor with `prior_outputs` (carried, not re-run) plus the
   approval — or halts on reject.
6. **`audit.py` — replayable trace.** Contract: `get_trace(run_id) -> dict` joins runs/plans/
   steps/events into one structure (per-step resolved inputs/outputs, events with `+ms` offsets,
   decisions, timings, the brief). Read-only — it persists nothing new.

**The minimal happy path in pseudocode** (the thing to write cold):

```python
registry = build_registry()                  # tools register == the allowlist
plan = build_plan(goal, registry, provider)  # provider may be None -> deterministic plan
#   asserts every step.tool in registry; sets step.consequential from the registry
run_id = create_run(goal); save_plan(run_id, plan)

outputs = dict(prior_outputs or {})          # empty on first run; seeded on resume
for step in plan.steps:
    if step.index in outputs:                # carried from a prior segment
        continue
    if step.consequential and not approved(step.index):
        pause(run_id, step); return          # checkpoint: stop before the effect
    inputs = resolve_refs(step.inputs, outputs)        # {"$ref": "stepN.field"}
    for attempt in range(1, max_attempts + 1):
        try:
            out = registry.call(step.tool, inputs)     # validates input AND output
            break
        except (SchemaValidationError, ToolNotAllowed):
            halt(run_id, step); return                 # deterministic failure -> no retry
        except Exception:
            if attempt == max_attempts: halt(run_id, step); return
            continue                                   # transient -> retry
    outputs[step.index] = out; record_step(run_id, step, out)
set_run_status(run_id, "completed")
```

**Non-core add-ons:** `app/main.py` (FastAPI + HTMX UI), `app/cli.py` (`python -m app.cli
"<goal>"` runs end-to-end auto-approving), `app/providers.py` (LLM abstraction), `app/seed.py`
(`make seed` / `make reset`). There is **no separate eval harness** — verification is the
`pytest` suite (`make test`).

**Self-check:** you can write the loop above from memory and explain why validation/disallowed
halt but a generic error retries.

---

## 4. Extend it to a new domain by swapping the "swap layer"

| Swap this | File | What changes |
|---|---|---|
| The tools (capabilities) | `app/tools/*.py` + `build_registry()` in `app/registry.py` | The actual work and each tool's typed input/output JSON Schema; mark the irreversible ones `consequential=True`. |
| The data the tools read | `data/corpus/documents.json` | The synthetic/public source `retrieve_documents` searches (or have a tool call a real API instead). |
| The sample goals | `data/demo_goals.seed.json` | The example prompts shown in the UI and used by `make seed`. |
| The "what needs a human" policy | the `consequential` flag on each tool (`app/tools/*`) | Which steps pause for approval — the registry is authoritative. |
| *(optional)* planning guidance | `_SYSTEM_PROMPT` in `app/planner.py`; `max_steps`/`max_attempts` on `Executor` | Only if a domain needs different planning hints or budgets. |

**The engine (what you DON'T touch):** `registry.py`, `planner.py` (core), `executor.py`,
`checkpoints.py`, `audit.py`, `store.py`, `providers.py`, `config.py`. These never name a
concrete tool — they operate on `registry.specs()` (names + schemas) and the `$ref` wiring.

**The recipe:**
1. Write the new tools in `app/tools/` with input/output JSON Schemas; flag consequential ones.
2. Register them in `build_registry()`.
3. Provide the domain data the tools read (drop a file under `data/`, or have the tool hit a
   real service).
4. Add a few sample goals to `data/demo_goals.seed.json`.
5. `make reset` → `make run`. The planner, executor, checkpoints, and audit are unchanged.
6. *(optional)* tune `_SYSTEM_PROMPT` and the executor budgets.

**Why it's this clean:** the executor and planner reach tools *only* through the registry's
schema specs, never through concrete handlers; the `consequential` gate is read from the
registry, not trusted from the model; and cross-step data flows through a generic `{"$ref":
"stepN.field"}` convention. Nothing in the engine knows the word "brief" or "green roofs."

**Self-check:** you can name the five swap points and the eight engine files, and explain why
adding a tool requires zero changes to `executor.py`.

---

## 5. Defend every design decision to a skeptic

**Why a plan-then-execute split instead of a single ReAct-style agent loop?** Because an
explicit, inspectable plan is what makes the system auditable, checkpoint-able, and
controllable — you can show it before anything runs, gate it, and replay it. A single-shot
loop is a black box that's hard to trust or stop. The accepted tradeoff is less free-form
flexibility, which is the point (002).

**What stops the model from doing something it shouldn't?** The registry is an allowlist:
the planner is only ever handed `registry.specs()`, and `registry.call` refuses any name it
doesn't hold — the agent literally cannot reach a tool it wasn't granted. Even if an LLM
hallucinates a tool into a plan, `planner` validates every step against the registry and
rejects it before persistence (003, 012).

**Why JSON Schema validated inside the registry's call path, not Pydantic models in the
executor?** JSON Schema is the MCP-aligned, language-agnostic contract — the *same* object
validates a call and describes the tool to the planner. Putting validation in `registry.call`
makes the call path itself the enforcement boundary, so nothing can call a tool incorrectly
even outside the executor (009).

**How do you prevent a runaway agent?** A deterministic cage around the non-deterministic
planner: a step/iteration budget (`max_steps`), retry-or-halt with a bounded `max_attempts`,
and schema validation between every step. The model is the creative, fallible part; the
guardrails are the predictable part (004, 013).

**Why retry some failures but halt on others?** Retrying a deterministic failure — a schema
violation or a disallowed tool — just burns the budget and reproduces the same error, so those
halt immediately and loudly. Retry is reserved for plausibly-transient tool/model errors. A
genuinely transient validation blip won't be retried; acceptable because the tools here are
deterministic (013).

**Why pause consequential steps instead of running and undoing on rejection?** Pausing *before*
the effect honors "never run a consequential step without approval" with no compensating logic.
The pause is a simple `{step_index: bool}` approvals seam the executor already honors, so the
interactive gate was additive, not a rewrite (005, 014).

**How does resume work without re-running everything?** `checkpoints.resume` reconstructs the
plan and already-succeeded outputs from SQLite and re-invokes the executor with `prior_outputs`
carried forward, so only the approved step onward runs. Because state lives in the DB, a paused
run survives a restart. It trusts persisted outputs rather than recomputing — fine for
deterministic tools, and anything re-run still re-validates (015).

**Why is the audit a derived projection rather than its own write path?** Execution already
persists everything needed (plans, steps with inputs/outputs, events, decisions), so `audit.
get_trace` just joins those tables. A second audit write path could drift from what actually
ran. "Replayable" means the trace is fully reconstructable from persisted state, which
`/runs/{id}/trace.json` makes explicit (006, 016).

**Anthropic by default but it runs with no key — isn't that a cop-out?** `providers.make_provider`
returns Anthropic, Ollama, or `None`; with no provider (or on provider failure) the planner
emits a deterministic built-in plan and records the real provider/model used, including a
`(fallback: …)` note. This keeps the demo cold-runnable and honest about what produced the
plan. Default model is `claude-sonnet-4-6` (011, 007).

**Why SQLite + HTMX instead of Postgres + a SPA?** One developer, must demo reliably and reset
in one command. SQLite stores runs/plans/steps/audit and resets instantly; HTMX gives a real
run viewer and approval UI with no build step. Revisit at concurrency or a richer UI (001).

**Show me a guardrail actually catching something.** Ask for an off-corpus goal (e.g. *"a brief
on quantum teleportation hardware"*): `retrieve_documents` filters stopwords/instruction words
and returns **zero** documents; the empty hand-off is rejected by `summarize_sources`' input
schema (`documents` requires ≥1), so the run halts `failed` with a `validation_failure` event
instead of summarizing nothing. The schema boundary is the safety net — no bespoke logic (017).

**The honest read on the metrics.** There is **no formal eval harness or accuracy number** in
this repo — the verification is the **37-test `pytest` suite** (`make test`), which is hermetic
(temp SQLite, deterministic planner, no network) and covers the allowlist boundary, schema
validation, the budget, retry, the checkpoint pause/approve/reject/resume, the guardrail trip,
and the audit reconstruction. Two honest caveats: (1) `summarize_sources` and `write_brief` are
**deterministic stubs**, so the "cited brief" is mechanically assembled, not model-written — the
schema is the contract so an LLM handler can drop in later (010); (2) the **live** Anthropic/
Ollama planning path is exercised only via a fake provider in tests, not a real API call in CI.

**Data & compliance posture.** Synthetic/public data only — a small bundled corpus, no PHI, no
internal systems; model + prompt version recorded on every plan (007). Real or sensitive data
would need controls this prototype doesn't have: a per-tool permission/cost policy, tool
sandboxing, role-based approvals, audit retention, and an appropriate data boundary — listed
under "Path to production" in `README.md`.

**Self-check:** for any decision a skeptic names, you can state the rejected alternative, the
`DECISIONS.md` id, and the caveat — without getting defensive.

---

### How to use this doc

Read it once start to finish, then **drill the self-checks** — they're the exam, not the prose.
You own this project when you can do all five cold: explain it in 60 seconds, draw the diagram
on a blank board, name the modules in build order and write the happy-path loop, list the swap
points and the untouched engine, and defend any decision with its rejected alternative and
honest caveat.

## Mastery checklist

```
- [ ] 1. Explain it in 60 seconds (domain + the anchor property), no notes
- [ ] 2. Draw the architecture from a blank board (stages, splits, external calls, guardrails)
- [ ] 3. Name the modules in build order, state each contract, write the happy path cold
- [ ] 4. List the swap-layer files, say what stays untouched and why
- [ ] 5. Defend any decision a skeptic names — alternative rejected + real numbers + caveats
```
