# SkillOpt Studio — common tasks. Wraps run.sh + the venv so you never touch bare python3.
VENV_PY := .venv/bin/python

.PHONY: help install install-geval doctor run test lint example clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

install: ## Create venv + install studio, SkillOpt engine, node deps (idempotent)
	./run.sh install

install-geval: ## Same as install, plus the DeepEval G-Eval grader extra
	./run.sh install --with-geval

doctor: ## Preflight: check every dependency and print a report
	./run.sh doctor

run: ## Launch backend + frontend
	./run.sh run

test: ## Run the backend test suite
	$(VENV_PY) -m pytest -q

lint: ## Ruff lint the backend
	$(VENV_PY) -m ruff check backend

example: ## Print the tutorial entrypoint for the bundled example
	@echo "Bundled example: examples/date-normalizer/"
	@echo "Follow the full self-evolve walkthrough in TUTORIAL.md"

clean: ## Remove venv, caches, and build artifacts (keeps your datasets/outputs)
	rm -rf .venv .pytest_cache backend/*.egg-info backend/skillopt_studio.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
