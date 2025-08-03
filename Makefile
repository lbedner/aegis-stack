# Aegis Stack Makefile

# Run the application locally via Docker
run-local: ## Run the application locally via Docker
	@docker compose --profile dev up webserver

# Run the application locally without Docker (for development)
run-dev: ## Run the application locally without Docker
	@uv run python -m app.entrypoints.webserver

# Run tests
test: ## Run tests
	@uv run pytest

# Run linting	
lint: ## Run linting with ruff
	@uv run ruff check .

# Run type checking
typecheck: ## Run type checking with mypy
	@uv run mypy .

# Run all checks (lint + typecheck + test)
check: lint typecheck test ## Run all checks

# Install dependencies
install: ## Install dependencies with uv
	@uv sync

# Clean up cache files
clean: ## Clean up cache files
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type f -name "*.pyc" -delete

# Serve documentation locally
docs-serve: ## Serve documentation locally with live reload on port 8001
	@uv run mkdocs serve --dev-addr 0.0.0.0:8001

# Build documentation
docs-build: ## Build the static documentation site
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

docker-webserver: ## Run webserver in Docker
	@docker compose --profile dev up webserver

docker-test: ## Run tests in Docker
	@docker compose --profile test run --rm test_runner

# Show help
help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $1, $2}'

.PHONY: run-local run-dev test lint typecheck check install clean docs-serve docs-build docker-build docker-up docker-down docker-logs docker-webserver docker-test help

# Default target
.DEFAULT_GOAL := help