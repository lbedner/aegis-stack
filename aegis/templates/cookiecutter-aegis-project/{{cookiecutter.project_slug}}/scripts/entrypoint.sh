#!/usr/bin/env bash

set -e

# More comprehensive venv cleanup to prevent Docker container conflicts
if [ -d ".venv" ]; then
    echo "🧹 Found existing .venv directory, checking compatibility..."
    
    # Check if .venv has issues (broken symlinks, wrong Python version, etc.)
    if [ -L ".venv/bin/python3" ] && [ ! -e ".venv/bin/python3" ]; then
        echo "🧹 Cleaning up broken venv symlinks..."
        rm -rf .venv
    elif [ -f ".venv/bin/python3" ]; then
        # Check if the Python executable is compatible and accessible
        if ! .venv/bin/python3 --version > /dev/null 2>&1; then
            echo "🧹 Cleaning up incompatible venv..."
            rm -rf .venv
        fi
    elif [ ! -w ".venv" ] || [ ! -x ".venv" ]; then
        # Check for permission issues in Docker containers
        echo "🧹 Cleaning up venv with permission issues..."
        rm -rf .venv
    else
        # If directory exists but has no python executable, clean it up
        if [ ! -f ".venv/bin/python3" ] && [ ! -f ".venv/bin/python" ]; then
            echo "🧹 Cleaning up incomplete venv..."
            rm -rf .venv
        fi
    fi
fi

# Configure UV environment based on execution context
if [ -n "$DOCKER_CONTAINER" ] || [ "$USER" = "root" ]; then
    echo "🐳 Running in Docker container, configuring UV for containerized environment..."
    
    # Set Docker-specific UV configuration
    export UV_PROJECT_ENVIRONMENT=/code/.venv
    export UV_LINK_MODE=copy
    export VIRTUAL_ENV=/code/.venv
    
    # Ensure .venv path is in PATH for CLI commands
    export PATH="/code/.venv/bin:$PATH"
    
    echo "✅ UV configured for Docker: UV_PROJECT_ENVIRONMENT=/code/.venv"
else
    echo "🖥️  Running in local environment, UV will use project defaults"
    
    # Ensure we don't inherit Docker environment variables
    unset UV_PROJECT_ENVIRONMENT
    unset UV_SYSTEM_PYTHON
    
    # Let UV auto-detect local .venv
    echo "✅ UV configured for local development"
fi

# Pop run_command from arguments
run_command="$1"
shift

if [ "$run_command" = "webserver" ]; then
    # Web server (FastAPI + Flet)
    uv run python -m app.entrypoints.webserver
elif [ "$run_command" = "scheduler" ]; then
    # Scheduler component
    uv run python -m app.entrypoints.scheduler
elif [ "$run_command" = "lint" ]; then
    uv run ruff check .
elif [ "$run_command" = "typecheck" ]; then
    uv run mypy .
elif [ "$run_command" = "test" ]; then
    uv run pytest "$@"
elif [ "$run_command" = "health" ]; then
    uv run python -m app.cli.health check "$@"
elif [ "$run_command" = "help" ]; then
    echo "Available commands:"
    echo "  webserver   - Run FastAPI + Flet web server"
    echo "  scheduler   - Run scheduler component"
    echo "  health      - Check system health status"
    echo "  lint        - Run ruff linting"
    echo "  typecheck   - Run mypy type checking"
    echo "  test        - Run pytest test suite"
    echo "  help        - Show this help message"
else
    echo "Unknown command: $run_command"
    echo "Available commands: webserver, scheduler, health, lint, typecheck, test, help"
    exit 1
fi