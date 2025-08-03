# Aegis Stack Makefile

# Run the application in web mode locally 
run-local: ## Run the application locally in web mode via uvicorn
	@uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

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

# Show help
help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $1, $2}'

.PHONY: run-local run-web test lint typecheck check install clean docs-serve docs-build help

# Default target
.DEFAULT_GOAL := help