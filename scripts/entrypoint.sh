#!/usr/bin/env bash

set -e

# Pop run_command from arguments
run_command="$1"
shift

if [ "$run_command" = "webserver" ]; then
    # Web server (FastAPI + Flet)
    uv run python -m app.entrypoints.webserver
elif [ "$run_command" = "lint" ]; then
    uv run ruff check .
elif [ "$run_command" = "typecheck" ]; then
    uv run mypy .
elif [ "$run_command" = "test" ]; then
    uv run pytest "$@"
elif [ "$run_command" = "help" ]; then
    echo "Available commands:"
    echo "  webserver   - Run FastAPI + Flet web server"
    echo "  lint        - Run ruff linting"
    echo "  typecheck   - Run mypy type checking"
    echo "  test        - Run pytest test suite"
    echo "  help        - Show this help message"
else
    echo "Unknown command: $run_command"
    echo "Available commands: webserver, lint, typecheck, test, help"
    exit 1
fi