# {{cookiecutter.project_name}} - Aegis Stack Project

# Environment isolation check
check-env:
	@if [ -n "$$VIRTUAL_ENV" ] && [ "$$(basename $$VIRTUAL_ENV)" != ".venv" ]; then \
		echo "⚠️  Warning: You're in a different virtual environment ($$VIRTUAL_ENV)"; \
		echo "   This may cause 'uv' warnings. Consider running: unset VIRTUAL_ENV"; \
	fi
	@if [ "$$VIRTUAL_ENV" = "/code/.venv" ]; then \
		echo "⚠️  Warning: You appear to be in a Docker environment ($$VIRTUAL_ENV)"; \
		echo "   For local development, run: unset VIRTUAL_ENV && source .venv/bin/activate"; \
	fi

# Run the application locally via Docker
run-local: ## Run the application locally via Docker (all dev services)
	@docker compose --profile dev up

# Run the application locally without Docker (for development)
run-dev: check-env ## Run the application locally without Docker
	@uv run python -m app.entrypoints.webserver

{% if cookiecutter.include_scheduler == "yes" %}# Run scheduler component locally
run-scheduler: check-env ## Run the scheduler component locally
	@uv run python -m app.entrypoints.scheduler{% endif %}

# Run tests
test: check-env ## Run tests
	@uv run pytest

# Health monitoring commands (with lazy CLI installation)
health: ensure-cli ## Show system health status (always exits 0)
	@uv run {{cookiecutter.project_slug}} health status

health-detailed: ensure-cli ## Show system health with detailed information
	@uv run {{cookiecutter.project_slug}} health status --detailed

health-json: ensure-cli ## Show system health and output as JSON
	@uv run {{cookiecutter.project_slug}} health status --json

health-probe: ensure-cli ## Health probe for monitoring (exits 1 if unhealthy)
	@uv run {{cookiecutter.project_slug}} health probe

# Fallback health commands using uv run (if CLI installation fails)
health-fallback: check-env ## Health status via uv run (fallback method)
	@echo "🔄 Using fallback method..."
	@uv run python -m app.cli.health status

# Run linting	
lint: check-env ## Run linting with ruff
	@uv run ruff check .

# Auto-fix linting and formatting issues
fix: check-env ## Auto-fix linting and formatting issues
	@uv run ruff check . --fix
	@uv run ruff format .

# Format code only
format: check-env ## Format code with ruff
	@uv run ruff format .

# Run type checking
typecheck: check-env ## Run type checking with mypy
	@uv run mypy .

# Run all checks (lint + typecheck + test)
check: ## Run all checks
	@echo "🔍 Running linting..."
	@$(MAKE) lint
	@echo "🔍 Running type checking..."
	@$(MAKE) typecheck  
	@echo "🔍 Running tests..."
	@$(MAKE) test
	@echo "✅ All checks completed successfully!"

# Install dependencies
install: check-env ## Install dependencies with uv
	uv sync --all-extras

# Ensure CLI commands are available (lazy installation)
ensure-cli: check-env
	@if ! uv run {{cookiecutter.project_slug}} --help >/dev/null 2>&1; then \
		echo "🔧 CLI command not found, installing automatically..."; \
		uv pip install -e . >/dev/null 2>&1; \
		if uv run {{cookiecutter.project_slug}} --help >/dev/null 2>&1; then \
			echo "✅ CLI command '{{cookiecutter.project_slug}}' installed successfully"; \
		else \
			echo "⚠️  CLI installation failed. Try: make install-cli"; \
		fi; \
	fi

# Manual CLI installation (for troubleshooting)
install-cli: check-env ## Manually install CLI command ({{cookiecutter.project_slug}})
	@echo "🔧 Installing CLI command for local development..."
	@uv pip install -e .
	@echo "✅ CLI command installed:"
	@echo "   uv run {{cookiecutter.project_slug}} health status          # Health status (always exits 0)"
	@echo "   uv run {{cookiecutter.project_slug}} health status --detailed"
	@echo "   uv run {{cookiecutter.project_slug}} health probe           # Health probe (exits 1 if unhealthy)"
	@echo "   uv run {{cookiecutter.project_slug}} --help"
	@echo ""
	@echo "💡 Alternative (activate virtual environment first):"
	@echo "   source .venv/bin/activate"
	@echo "   {{cookiecutter.project_slug}} health status"
	@echo "   {{cookiecutter.project_slug}} health probe"

# Clean up cache files
clean: ## Clean up cache files
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type f -name "*.pyc" -delete

# Serve documentation locally
docs-serve: check-env ## Serve documentation locally with live reload on port 8001
	@uv run mkdocs serve --dev-addr 0.0.0.0:8001

# Build documentation
docs-build: check-env ## Build the static documentation site
	@uv run mkdocs build

# Docker commands
docker-build: ## Build the Docker image
	@docker build -t aegis-stack:latest .

docker-up: ## Start development services
	@docker compose --profile dev up -d

docker-down: ## Stop all services
	@docker compose down

docker-logs: ## Follow logs for all services
	@docker compose logs -f

docker-webserver: ## Run only webserver service in Docker
	@docker compose --profile dev up webserver

{% if cookiecutter.include_scheduler == "yes" %}docker-scheduler: ## Run only scheduler service in Docker
	@docker compose --profile dev up scheduler{% endif %}

docker-test: ## Run tests in Docker
	@docker compose --profile test run --rm test_runner

# Show help
help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $1, $2}'

.PHONY: run-local run-dev{% if cookiecutter.include_scheduler == "yes" %} run-scheduler{% endif %} test health health-detailed health-json health-probe health-fallback lint fix format typecheck check install ensure-cli install-cli clean docs-serve docs-build docker-build docker-up docker-down docker-logs docker-webserver{% if cookiecutter.include_scheduler == "yes" %} docker-scheduler{% endif %} docker-test help

# Default target
.DEFAULT_GOAL := help