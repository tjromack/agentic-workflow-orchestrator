# Agentic Workflow Orchestrator — developer commands.
# Cross-platform venv path (Windows uses Scripts/, POSIX uses bin/).

ifeq ($(OS),Windows_NT)
	PY := .venv/Scripts/python.exe
else
	PY := .venv/bin/python
endif

.PHONY: install seed run test reset fmt

install:        ## Create venv + install dependencies
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt

seed:           ## Register demo tools + sample goals (Phase 1)
	@echo "seed: implemented in Phase 1 (tool registry + sample goals)."

run:            ## Start the FastAPI dev server
	$(PY) -m uvicorn app.main:app --reload

test:           ## Run the test suite
	$(PY) -m pytest -q

reset:          ## Clear runs + re-seed for a clean demo (Phase 1+)
	@echo "reset: implemented in Phase 1 (clear DB + re-seed)."

fmt:            ## Format code (placeholder until a formatter is wired)
	@echo "fmt: no formatter configured yet."
