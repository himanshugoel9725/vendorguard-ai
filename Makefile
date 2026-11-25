# VendorGuard AI developer commands. Everything is offline and free unless a target says otherwise.
.DEFAULT_GOAL := help

# The repository lives in an iCloud-synced folder, which corrupts a virtual environment named .venv
# (hidden-file flags, conflict copies, a renamed symlink). Keep it where iCloud ignores it, and do
# not create a `.venv` at all: run uv through this variable (point your editor at .venv.nosync).
export UV_PROJECT_ENVIRONMENT ?= .venv.nosync

.PHONY: help setup fmt lint type test check hf test-live test-hosted sample record eval api \
        docker-build docker-up docker-down demo-memory letta-up letta-down docs docs-config ui doctor clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup: ## Install all dependencies and the git pre-commit hook
	uv sync --all-groups
	uv run pre-commit install

fmt: ## Auto-format and auto-fix lint issues
	uv run ruff format .
	uv run ruff check --fix .

lint: ## Ruff lint and format check
	uv run ruff check .
	uv run ruff format --check .

type: ## mypy strict on src/
	uv run mypy

test: ## Offline tests with mock providers and a coverage report
	uv run pytest --cov --cov-report=term-missing:skip-covered

check: lint type test ## Fast offline gate: ruff + mypy + pytest

hf: ## Fail if any Hugging Face package, import or endpoint appears
	bash scripts/check_no_hf.sh

test-live: ## Tests that need local Ollama / Letta / a Jev key (skipped by default)
	uv run pytest -o addopts="" -m "ollama or letta or jev"

test-hosted: ## One tiny real call per hosted LLM with a key set (OpenAI spends a few cents; asks nothing else)
	uv run pytest -o addopts="" -m hosted tests/live -s -q --no-cov

sample: ## Generate the synthetic sample vendors and golden labels (deterministic)
	uv run python scripts/make_samples.py

record: ## Re-record replay cassettes with local Ollama (sequential; BM25 retrieval so CI needs no embedder)
	@for spec in data/samples/specs/*.yaml; do \
	  v=$$(basename $$spec .yaml); \
	  VG_CACHE__BACKEND=jsonl VG_CACHE__MODE=read_write VG_EMBEDDINGS__PROVIDER=none \
	    uv run vg assess --sample $$v || exit 1; \
	done

eval: ## Run the evaluation matrix
	uv run vg eval

api: ## Start the REST API (host and port come from config/settings.yaml)
	uv run python -m vendorguard.api.app

docker-build: ## Build the API image (needs Docker)
	docker build -t vendorguard-ai:local .

docker-up: ## Start the API in Docker (needs Docker and VG_API__AUTH_KEY in .env)
	docker compose --profile api up --build -d

docker-down: ## Stop the API container
	docker compose --profile api down

demo-memory: ## Offline demo: nimbara-hr year 1, year 2, the diff, and a question
	bash scripts/memory_demo.sh

letta-up: ## (not built: Letta is deferred, ADR-019)
	@echo 'Letta is not built yet (ADR-019); SQLite is the only memory store.'; exit 1

letta-down: ## (not built: Letta is deferred, ADR-019)
	@echo 'Letta is not built yet (ADR-019); SQLite is the only memory store.'; exit 1

docs: ## Build the MkDocs site (warnings are errors)
	uv run mkdocs build --strict

ui: ## Start the Streamlit UI on 127.0.0.1:8501 (needs `make api` and VG_UI__API_KEY)
	uv run --group ui streamlit run src/vendorguard/ui/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false

docs-config: ## Regenerate docs/CONFIG.md from the Settings models and YAML comments
	uv run python scripts/gen_config_docs.py

doctor: ## Check config, provider reachability and keys (set/unset only)
	uv run vg doctor

clean: ## Remove caches and build output (keeps .vendorguard/ and data/)
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml dist build site
	find . -name __pycache__ -type d -not -path "./.venv/*" -prune -exec rm -rf {} +
