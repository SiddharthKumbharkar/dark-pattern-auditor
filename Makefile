.PHONY: help setup test lint demo clean

PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python3

help:
	@echo "Targets:"
	@echo "  make setup  - create .venv, install dependencies, install the Playwright browser"
	@echo "  make test   - run the full test suite (python3 -m pytest -q)"
	@echo "  make lint   - ruff check . (syntax errors + real bugs: unused imports/vars, undefined names)"
	@echo "  make demo   - run the guided Auralis known-answer test suite (dpa.py run-demo-suite)"
	@echo "  make clean  - remove __pycache__/.pytest_cache/.ruff_cache and *.pyc (never touches storage/ or payload/)"

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -r requirements-dev.txt
	$(VENV_PYTHON) -m playwright install chromium
	@echo "Done. Activate with: source $(VENV)/bin/activate"

test:
	$(PYTHON) -m pytest -q

# Scoped to syntax errors (E9) and pyflakes' real-bug checks (F: unused
# imports/variables, undefined names) rather than ruff's full opinionated
# default ruleset -- this codebase has never been run through a style
# linter, and a "make lint" that immediately buries a first-time user in
# hundreds of style-only findings is worse than one that catches genuine
# bugs cleanly. Run `ruff check .` directly for the fuller style ruleset.
lint:
	ruff check . --select=E9,F

# The Auralis dev server (demo-site/ or demo-site-vite/, `npm run dev`,
# default :3000) must already be running -- this target does not manage
# it, since the dev server and this pipeline are separate, independently
# restartable processes. See README.md's "Running the Auralis demo suite"
# section for the full walkthrough.
demo:
	$(PYTHON) dpa.py run-demo-suite

# Deliberately does NOT remove storage/, payload/, logs/, or
# ground_truth.yaml -- those hold real recorded episodes and audit
# history, not build artifacts, and deleting them is never something
# this target should do silently.
clean:
	find . -type d -name "__pycache__" -not -path "./node_modules/*" -exec rm -rf {} +
	find . -type f -name "*.pyc" -not -path "./node_modules/*" -delete
	rm -rf .pytest_cache .ruff_cache
