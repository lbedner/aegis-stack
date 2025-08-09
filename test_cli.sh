#!/bin/bash
# Aegis Stack CLI Test Runner
# 
# This script demonstrates how to run the CLI test suite in different modes.

set -e  # Exit on error

echo "🛡️  Aegis Stack CLI Test Suite"
echo "================================"

# Function to run tests with nice output
run_tests() {
    local description=$1
    local command=$2
    
    echo ""
    echo "📋 $description"
    echo "Running: $command"
    echo "---"
    
    if eval "$command"; then
        echo "✅ $description - PASSED"
    else
        echo "❌ $description - FAILED"
        exit 1
    fi
}

# Install dependencies
echo "📦 Installing dependencies..."
uv sync --all-extras

# Run basic CLI tests (fast)
run_tests "Basic CLI Tests (fast)" \
    "uv run pytest tests/cli/test_cli_basic.py -v"

# Run specific integration test
run_tests "Single Integration Test" \
    "uv run pytest tests/cli/test_cli_init.py::TestCLIInit::test_init_with_scheduler_component --runslow -v"

# Run all fast tests
run_tests "All Fast Tests" \
    "uv run pytest tests/ -v -m 'not slow'"

echo ""
echo "🚀 Fast tests completed successfully!"
echo ""
echo "To run slow integration tests (full project generation):"
echo "  uv run pytest tests/cli/test_cli_init.py --runslow -v"
echo ""
echo "To run ALL tests including slow ones:"
echo "  uv run pytest tests/ --runslow -v"
echo ""
echo "Test Categories:"
echo "  • Basic CLI tests: Command parsing, help text, validation"
echo "  • Integration tests: Full project generation and validation"
echo "  • Quality tests: Generated projects pass linting/type checking"