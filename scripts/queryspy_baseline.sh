#!/bin/bash
# Regenerate tests/fixtures/queryspy-baseline.json: generate every database
# stack from the working-tree templates, record its findings, merge.
#
# Entries key on (kind, label, file, function) with paths relative to the
# generated project, so one file serves the whole matrix. The label of a
# repeated_statement is the statement text, so a column added to a model
# changes every entry for that table: after a schema change on a service,
# run this or the matrix fails on entries that are only stale.
#
# Each stack's findings land in tests/fixtures/queryspy/<stack>.json and
# the shipped baseline is their union, so sweeping one stack can never
# touch another's rows.
#
#   make queryspy-baseline               # all database stacks (~40 min)
#   make queryspy-baseline STACKS=finance,finance_auth,everything
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${QUERYSPY_SWEEP_DIR:-$(mktemp -d /tmp/queryspy-sweep.XXXXXX)}"
ONLY="${STACKS:-}"
mkdir -p "$OUT/baselines" "$REPO/tests/fixtures/queryspy"
cd "$REPO" || exit 1

uv run python - > "$OUT/stacks.txt" <<'PY'
from tests.cli.test_stack_generation import STACK_COMBINATIONS as S
for c in S:
    print(f"{c.name}|{','.join(c.components or [])}|{','.join(c.services or [])}")
PY

while IFS='|' read -r name comps svcs; do
  [ -z "$name" ] && continue
  if [ -n "$ONLY" ] && ! grep -qx "$name" <<<"${ONLY//,/$'\n'}"; then continue; fi
  slug="${name//_/-}"; proj="$OUT/$slug"; rm -rf "$proj"
  args=(init "$slug" --dev --no-interactive --output-dir "$OUT")
  [ -n "$comps" ] && args+=(-c "$comps")
  [ -n "$svcs" ] && args+=(-s "$svcs")
  yes | uv run aegis "${args[@]}" > "$OUT/$name.gen.log" 2>&1 || { echo "$name: GENERATE FAILED ($OUT/$name.gen.log)"; continue; }
  grep -q queryspy "$proj/pyproject.toml" 2>/dev/null || { echo "$name: no database, skipped"; continue; }
  ( cd "$proj" && uv sync > "$OUT/$name.sync.log" 2>&1 ) || { echo "$name: SYNC FAILED"; continue; }
  ( cd "$proj" && uv run pytest -q --queryspy-baseline="$OUT/baselines/$name.json" --queryspy-baseline-update > "$OUT/$name.qs.log" 2>&1 )
  echo "$name: $(grep -oE '[0-9]+ (passed|failed)' "$OUT/$name.qs.log" | tr '\n' ' ')"
done < "$OUT/stacks.txt"

# Each stack owns its own file under tests/fixtures/queryspy/, so a
# partial sweep rewrites only the stacks it ran. The shipped baseline is
# the union of all of them. Merging into one file used to lose that
# ownership: the union kept old rows only when their FILE appeared in no
# fresh baseline, so sweeping a broad stack like ``everything`` replaced
# the rows of every service it covers and silently narrowed the narrow
# stacks that also touch those files.
for f in "$OUT"/baselines/*.json; do
  [ -e "$f" ] || continue
  cp "$f" "$REPO/tests/fixtures/queryspy/$(basename "$f")"
done

uv run python - "$REPO/tests/fixtures/queryspy" "$REPO/tests/fixtures/queryspy-baseline.json" <<'PY'
import json, sys, glob, pathlib
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
key = lambda e: (e["kind"], e["label"], e["file"], e["function"])
merged = {}
for f in sorted(glob.glob(f"{src}/*.json")):
    for e in json.load(open(f))["entries"]:
        merged[key(e)] = e
doc = {"tool": "queryspy", "version": "0.4.1",
       "entries": sorted(merged.values(), key=lambda e: (e["kind"], e["label"], e["file"] or "", e["function"] or ""))}
dst.write_text(json.dumps(doc, indent=2) + "\n")
# Generated projects ship the same file so their CI gate starts from the
# template's known debt instead of failing on it.
shipped = dst.parents[2] / "aegis/templates/copier-aegis-project/{{ project_slug }}/.queryspy-baseline.json"
shipped.write_text(dst.read_text())
stacks = len(glob.glob(f"{src}/*.json"))
print(f"wrote {dst}: {len(doc['entries'])} entries from {stacks} stacks")
PY
