"""FastAPI application entry point.

Pose a goal -> inspectable plan -> guarded stepwise execution -> human checkpoint
-> persisted, replayable run trace. The trace is always rendered from persisted
state so /run and /resume show the same, complete picture.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app import checkpoints, store
from app.config import load_settings
from app.executor import Executor
from app.paths import SEED_GOALS
from app.planner import build_plan
from app.providers import make_provider
from app.registry import build_registry

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init_db()
    yield


app = FastAPI(title="Agentic Workflow Orchestrator", lifespan=lifespan)

# Built once: the registry (allowlist), settings, and configured provider.
_registry = build_registry()
_settings = load_settings()


def _seed_goals() -> list[dict]:
    if SEED_GOALS.exists():
        return json.loads(SEED_GOALS.read_text(encoding="utf-8")).get("goals", [])
    return []


def _render_run(request: Request, run_id: str) -> HTMLResponse:
    """Build the run trace from persisted state and render it."""
    run = store.get_run(run_id)
    steps = store.get_steps(run_id)
    brief = None
    for s in steps:
        if s["tool"] == "write_brief" and s["status"] == "succeeded" and s["output_json"]:
            brief = json.loads(s["output_json"]).get("brief_markdown")
    return templates.TemplateResponse(
        request,
        "_run.html",
        {
            "run": run,
            "steps": steps,
            "events": store.get_events(run_id),
            "pending_index": checkpoints.pending_checkpoint(run_id),
            "brief": brief,
        },
    )


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "title": "Agentic Workflow Orchestrator",
            "goals": _seed_goals(),
            "tools": _registry.specs(),
        },
    )


@app.post("/plan", response_class=HTMLResponse)
def plan(request: Request, goal: str = Form(...)) -> HTMLResponse:
    """Produce, persist, and render an inspectable plan for a goal."""
    provider = make_provider(_settings)
    plan_obj = build_plan(goal, _registry, provider)

    run_id = store.create_run(goal)
    store.save_plan(run_id, plan_obj)

    return templates.TemplateResponse(
        request,
        "_plan.html",
        {"run_id": run_id, "plan": plan_obj},
    )


@app.post("/run", response_class=HTMLResponse)
def run(request: Request, goal: str = Form(...)) -> HTMLResponse:
    """Plan, persist, then execute under guardrails (pausing at checkpoints)."""
    provider = make_provider(_settings)
    plan_obj = build_plan(goal, _registry, provider)

    run_id = store.create_run(goal)
    store.save_plan(run_id, plan_obj)

    Executor(_registry).run(run_id, plan_obj)
    return _render_run(request, run_id)


@app.post("/resume", response_class=HTMLResponse)
def resume(
    request: Request, run_id: str = Form(...), decision: str = Form(...)
) -> HTMLResponse:
    """Record the human decision and resume (approve) or halt (reject)."""
    checkpoints.resume(_registry, run_id, decision)
    return _render_run(request, run_id)
