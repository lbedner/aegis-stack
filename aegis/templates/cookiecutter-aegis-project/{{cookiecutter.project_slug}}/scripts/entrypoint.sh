#!/usr/bin/env bash

set -e

# Pop run_command from arguments
run_command="$1"
shift

if [ "$run_command" = "webserver" ]; then
    # Web server (FastAPI + Flet)
    uv run python -m app.entrypoints.webserver{% if cookiecutter.include_scheduler == "yes" %}
elif [ "$run_command" = "scheduler" ]; then
    # Scheduler component
    uv run python -m app.entrypoints.scheduler{% endif %}
elif [ "$run_command" = "lint" ]; then
    uv run ruff check .
elif [ "$run_command" = "typecheck" ]; then
    uv run mypy .
elif [ "$run_command" = "test" ]; then
    uv run pytest "$@"
elif [ "$run_command" = "help" ]; then
    echo "Available commands:"
    echo "  webserver   - Run FastAPI + Flet web server"{% if cookiecutter.include_scheduler == "yes" %}
    echo "  scheduler   - Run scheduler component"{% endif %}
    echo "  lint        - Run ruff linting"
    echo "  typecheck   - Run mypy type checking"
    echo "  test        - Run pytest test suite"
    echo "  help        - Show this help message"
else
    echo "Unknown command: $run_command"
    echo "Available commands: webserver{% if cookiecutter.include_scheduler == "yes" %}, scheduler{% endif %}, lint, typecheck, test, help"
    exit 1
fi