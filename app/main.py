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

from app import audit, checkpoints, store
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


def _render_trace(request: Request, run_id: str) -> HTMLResponse:
    """Render the live run partial from the assembled audit trace."""
    return templates.TemplateResponse(
        request, "_trace.html", {"trace": audit.get_trace(run_id)}
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
    return _render_trace(request, run_id)


@app.post("/resume", response_class=HTMLResponse)
def resume(
    request: Request, run_id: str = Form(...), decision: str = Form(...)
) -> HTMLResponse:
    """Record the human decision and resume (approve) or halt (reject)."""
    checkpoints.resume(_registry, run_id, decision)
    return _render_trace(request, run_id)


@app.get("/runs", response_class=HTMLResponse)
def runs_list(request: Request) -> HTMLResponse:
    """The audit log: every run, inspectable after the fact."""
    return templates.TemplateResponse(
        request, "runs_list.html",
        {"title": "Runs — audit log", "runs": audit.list_runs()},
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_view(request: Request, run_id: str) -> HTMLResponse:
    """Full viewer for a single run, reconstructed from the audit log."""
    trace = audit.get_trace(run_id)
    if trace is None:
        return HTMLResponse("Run not found", status_code=404)
    return templates.TemplateResponse(
        request, "run_view.html", {"title": "Run viewer", "trace": trace}
    )


@app.get("/runs/{run_id}/trace.json")
def run_trace_json(run_id: str) -> JSONResponse:
    """The machine-replayable trace artifact."""
    trace = audit.get_trace(run_id)
    if trace is None:
        return JSONResponse({"error": "run not found"}, status_code=404)
    return JSONResponse(trace)
