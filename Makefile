# Agentic Workflow Orchestrator — developer commands.
# Cross-platform venv path (Windows uses Scripts/, POSIX uses bin/).

ifeq ($(OS),Windows_NT)
	PY := .venv/Scripts/python.exe
else
	PY := .venv/bin/python
endif

.PHONY: install seed run test guardrails reset fmt

install:        ## Create venv + install dependencies
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt

seed:           ## Register demo tools + load sample goals
	$(PY) -m app.seed

run:            ## Start the FastAPI dev server
	$(PY) -m uvicorn app.main:app --reload

test:           ## Run the test suite
	$(PY) -m pytest -q

guardrails:     ## Exercise every guardrail and print the behaviour table (EVAL.md)
	$(PY) -m app.guardrails

reset:          ## Clear runs + re-seed for a clean demo
	$(PY) -m app.seed --reset

fmt:            ## Format code (placeholder until a formatter is wired)
	@echo "fmt: no formatter configured yet."
