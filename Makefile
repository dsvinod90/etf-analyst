VENV := .venv
BIN := $(VENV)/bin

.PHONY: help venv lint format typecheck test check clean

help:  ## Show the available targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

venv: $(BIN)/activate  ## Create .venv: the package (editable, with its commands) + pinned dev tools
$(BIN)/activate: requirements-dev.txt pyproject.toml
	python3 -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip
	$(BIN)/pip install --quiet -r requirements-dev.txt -e .
	touch $@

lint: venv  ## Lint Python (ruff) and the shell script (shellcheck)
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	shellcheck run-report.sh

format: venv  ## Auto-format and apply safe lint fixes
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

typecheck: venv  ## Strict type checking (mypy)
	$(BIN)/mypy

test: venv  ## Run the test suite with coverage
	$(BIN)/pytest

check: lint typecheck test  ## Everything CI runs; must pass before committing

clean:  ## Remove caches and the virtualenv
	rm -rf $(VENV) .mypy_cache .pytest_cache .ruff_cache .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
