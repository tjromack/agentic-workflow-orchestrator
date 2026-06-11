"""FastAPI application entry point.

Phase 0: boots the server, exposes a health check, and renders the base
template. Planner/executor/checkpoint/audit routes are added in later phases.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Agentic Workflow Orchestrator")


@app.get("/health")
def health() -> JSONResponse:
    """Liveness probe — used by `make run` smoke checks and the test suite."""
    return JSONResponse({"status": "ok"})


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Landing page. Becomes the run launcher + viewer in later phases."""
    return templates.TemplateResponse(
        request,
        "index.html",
        {"title": "Agentic Workflow Orchestrator"},
    )
