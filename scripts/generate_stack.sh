#!/bin/bash
# Generate one stack of the matrix (STACK_COMBINATIONS in
# tests/cli/test_stack_generation.py) from the working-tree templates of the
# repo in the current directory, into <output-dir>/<name, dashed>.
#
#   scripts/generate_stack.sh <name> <output-dir>
set -eu
name="$1"
out="$2"
IFS='|' read -r comps svcs < <(uv run python - "$name" <<'PY'
import sys

from tests.cli.test_stack_generation import STACK_COMBINATIONS

c = next(c for c in STACK_COMBINATIONS if c.name == sys.argv[1])
print(f"{','.join(c.components or [])}|{','.join(c.services or [])}")
PY
)
args=(init "${name//_/-}" --dev --no-interactive --output-dir "$out")
[ -n "$comps" ] && args+=(-c "$comps")
[ -n "$svcs" ] && args+=(-s "$svcs")
yes | uv run aegis "${args[@]}"
