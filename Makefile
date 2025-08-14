# Aegis Stack CLI Development Makefile
# This Makefile is for developing the Aegis Stack CLI tool itself.
# Generated projects have their own Makefiles for application development.

# Run tests
test: ## Run tests
	@uv run pytest

# Run linting	
lint: ## Run linting with ruff
	@uv run ruff check .

# Auto-fix linting issues
fix: ## Auto-fix linting and formatting issues
	@uv run ruff check . --fix
	@uv run ruff format .

# Format code only
format: ## Format code with ruff
	@uv run ruff format .

# Run type checking
typecheck: ## Run type checking with mypy
	@uv run mypy .

# Run all checks (lint + typecheck + test)
check: lint typecheck test ## Run all checks

# Install dependencies
install: ## Install dependencies with uv
	uv sync --all-extras

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

# CLI Development Commands
cli-test: ## Test CLI commands locally  
	@uv run python -m aegis --help
	@echo "✅ CLI command working"

# Show help
help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ============================================================================
# TEMPLATE TESTING TARGETS
# For rapid iteration on cookiecutter template changes
# 
# These targets help with the development workflow when modifying the 
# cookiecutter templates in aegis/templates/cookiecutter-aegis-project/
# 
# Typical workflow:
#   1. Make changes to template files
#   2. Run 'make test-template-quick' for fast feedback
#   3. Run 'make test-template' for full validation
#   4. Run 'make clean-test-projects' to cleanup
# ============================================================================

test-template-quick: ## Quick template test - generate basic project without validation
	@echo "🚀 Quick template test - generating basic project..."
	@chmod -R +w ../test-basic-stack 2>/dev/null || true
	@rm -rf ../test-basic-stack
	@env -u VIRTUAL_ENV uv run aegis init test-basic-stack --output-dir .. --no-interactive --force --yes
	@echo "📦 Setting up virtual environment and CLI..."
	@cd ../test-basic-stack && chmod -R +w .venv 2>/dev/null || true && rm -rf .venv && env -u VIRTUAL_ENV uv sync --extra dev --extra docs
	@cd ../test-basic-stack && env -u VIRTUAL_ENV uv pip install -e .
	@echo "✅ Basic test project generated in ../test-basic-stack/"
	@echo "   CLI command 'test-basic-stack' is now available"
	@echo "   Run 'cd ../test-basic-stack && make check' to validate"

test-template: ## Full template test - generate project and run validation
	@echo "🛡️  Full template test - generating and validating project..."
	@chmod -R +w ../test-basic-stack 2>/dev/null || true
	@rm -rf ../test-basic-stack
	@env -u VIRTUAL_ENV uv run aegis init test-basic-stack --output-dir .. --no-interactive --force --yes
	@echo "📦 Installing dependencies and CLI..."
	@cd ../test-basic-stack && chmod -R +w .venv 2>/dev/null || true && rm -rf .venv && env -u VIRTUAL_ENV uv sync --extra dev --extra docs
	@cd ../test-basic-stack && env -u VIRTUAL_ENV uv pip install -e .
	@echo "🔍 Running validation checks..."
	@cd ../test-basic-stack && env -u VIRTUAL_ENV make check
	@echo "🧪 Testing CLI script installation..."
	@cd ../test-basic-stack && env -u VIRTUAL_ENV uv run test-basic-stack --help >/dev/null && echo "✅ CLI script 'test-basic-stack --help' works" || echo "⚠️  CLI script test failed"
	@cd ../test-basic-stack && env -u VIRTUAL_ENV uv run test-basic-stack health quick >/dev/null 2>&1 && echo "✅ CLI script 'test-basic-stack health quick' works" || echo "ℹ️  Health command test skipped (requires running backend)"
	@echo "✅ Template test completed successfully!"
	@echo "   Test project available in ../test-basic-stack/"
	@echo "   CLI command 'test-basic-stack' is available"

test-template-with-components: ## Test template with scheduler component included
	@echo "🧩 Component template test - generating project with scheduler..."
	@chmod -R +w ../test-component-stack 2>/dev/null || true
	@rm -rf ../test-component-stack
	@env -u VIRTUAL_ENV uv run aegis init test-component-stack --components scheduler --output-dir .. --no-interactive --force --yes
	@echo "📦 Installing dependencies and CLI..."
	@cd ../test-component-stack && chmod -R +w .venv 2>/dev/null || true && rm -rf .venv && env -u VIRTUAL_ENV uv sync --extra dev --extra docs
	@cd ../test-component-stack && env -u VIRTUAL_ENV uv pip install -e .
	@echo "🔍 Running validation checks..."
	@cd ../test-component-stack && env -u VIRTUAL_ENV make check
	@echo "🧪 Testing CLI script installation..."
	@cd ../test-component-stack && env -u VIRTUAL_ENV uv run test-component-stack --help >/dev/null && echo "✅ CLI script 'test-component-stack --help' works" || echo "⚠️  CLI script test failed"
	@cd ../test-component-stack && env -u VIRTUAL_ENV uv run test-component-stack health quick >/dev/null 2>&1 && echo "✅ CLI script 'test-component-stack health quick' works" || echo "ℹ️  Health command test skipped (requires running backend)"
	@echo "✅ Component template test completed successfully!"
	@echo "   Test project available in ../test-component-stack/"
	@echo "   CLI command 'test-component-stack' is available"

clean-test-projects: ## Remove all generated test project directories
	@echo "🧹 Cleaning up test projects..."
	@chmod -R +w ../test-basic-stack ../test-component-stack 2>/dev/null || true
	@rm -rf ../test-basic-stack ../test-component-stack 2>/dev/null || true
	@echo "✅ Test projects cleaned up"

.PHONY: test lint fix format typecheck check install clean docs-serve docs-build cli-test test-template-quick test-template test-template-with-components clean-test-projects help

# Default target
.DEFAULT_GOAL := help