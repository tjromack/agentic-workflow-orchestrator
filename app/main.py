"""FastAPI application entry point.

Phase 2 adds a planner demo: pose a goal, get an explicit, inspectable plan
(persisted, with model + prompt version) that references only allowlisted tools.
Execution/checkpoints/audit-viewer arrive in later phases.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app import store
from app.config import load_settings
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
