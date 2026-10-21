#!/bin/bash
# Upgrade-path check across stack shapes: init each stack at FROM, `update` to
# TO, then count conflict markers / .rej files / stray worker-backend variants
# and run `make check`.
# ADD / ADD_SERVICES (comma lists) then run `aegis add` / `add-service` on each
# updated stack, so components new in the release are also tested on projects
# made before it. With ADD_SERVICES, two more shapes run: the services added
# then removed again (remove-service), and a stack made at TO with them that
# then adds a dramatiq worker (the reverse order).
# usage: FROM=0.14.0 TO=0.15.0rc1 [INDEX=testpypi|pypi] [ADD=mcp] [ADD_SERVICES=research] upgrade_stacks.sh <workdir>
: "${FROM:?set FROM}" "${TO:?set TO}"
work=${1:?workdir}; mkdir -p "$work"; cd "$work"; work=$(pwd)
I=()
[ "${INDEX:-testpypi}" = testpypi ] && I=(--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ --index-strategy unsafe-best-match)
# --refresh: a version published minutes ago is missing from a cached index.
# And retried: TestPyPI's mirrors catch up at different times, so one call
# can still miss a version another call just found.
aeg() {
  local out rc
  for _ in 1 2 3 4 5 6; do
    out=$(uvx --refresh "${I[@]}" "aegis-stack@$1" "${@:2}" 2>&1); rc=$?
    grep -qE "No solution found|no version of" <<<"$out" || break
    sleep 30
  done
  printf '%s\n' "$out"
  return $rc
}
commit() { git add -A; git commit -qm "$1" --no-verify >/dev/null 2>&1; }

# The tests that drive a live browser, when a browser container is up. Stacks
# run side by side and would share that one browser, so these run apart from
# make check, one stack at a time (a mkdir lock: macOS has no flock).
BROWSER_TESTS=(tests/components/test_browser.py tests/services/test_meet_page.py tests/services/test_meetings_audio.py)

verdict() {
  markers=$(grep -rlE '^(<<<<<<<|>>>>>>>)( |$)' --exclude-dir=.venv --exclude-dir=.git . | wc -l | tr -d ' ')
  rej=$(find . -name '*.rej' -not -path './.venv/*' | wc -l | tr -d ' ')
  stray=$(ls app/components/worker/queues 2>/dev/null | grep -cE '_(taskiq|dramatiq)\.py$')
  PYTEST_ADDOPTS="${BROWSER_TESTS[*]/#/--ignore=}" make check > "../$1.check.log" 2>&1; rc=$?
  present=(); for t in "${BROWSER_TESTS[@]}"; do [ -f "$t" ] && present+=("$t"); done
  if [ ${#present[@]} -gt 0 ]; then
    until mkdir "$work/.browser.lock" 2>/dev/null; do sleep 2; done
    uv run pytest -q -p no:cacheprovider "${present[@]}" > "../$1.browser.log" 2>&1 || rc=1
    rmdir "$work/.browser.lock"
  fi
  echo "$1: markers=$markers rej=$rej stray=$stray check_exit=$rc $(grep -E '[0-9]+ (passed|failed)' "../$1.check.log" | tail -1)"
}

# A version published minutes ago may not resolve yet, even with --refresh.
for _ in $(seq 1 30); do
  aeg "$TO" --version 2>&1 | grep -qE "No solution found|no version of" || break
  sleep 20
done

# name, components, services: init at FROM, update to TO, add what is new.
run() {
  name=$1; comps=$2; svcs=$3
  rm -rf "$name"
  args=(init "$name" --no-interactive -y --skip-llm-sync)
  [ -n "$comps" ] && args+=(-c "$comps"); [ -n "$svcs" ] && args+=(-s "$svcs")
  aeg "$FROM" "${args[@]}" > "$name.init.log" 2>&1 || { echo "$name: INIT FAILED"; return; }
  [ -d "$name" ] || { echo "$name: NO PROJECT DIR"; return; }
  ( cd "$name"
    [ -d .git ] || git init -q; commit base
    aeg "$TO" update -y > "../$name.update.log" 2>&1 || { echo "$name: UPDATE FAILED"; exit; }
    # add/add-service refuse a dirty tree; markers and .rej files are still found once committed
    commit update
    [ -n "${ADD:-}" ] && { aeg "$TO" add "$ADD" -y > "../$name.add.log" 2>&1 || { echo "$name: ADD FAILED"; exit; }; }
    [ -n "${ADD_SERVICES:-}" ] && { aeg "$TO" add-service "$ADD_SERVICES" -y > "../$name.add-service.log" 2>&1 || { echo "$name: ADD-SERVICE FAILED"; exit; }; }
    if [ "${4:-}" = remove ]; then
      commit added
      aeg "$TO" remove-service "$ADD_SERVICES" -y > "../$name.remove.log" 2>&1 || { echo "$name: REMOVE FAILED"; exit; }
    fi
    verdict "$name" )
}

# Made at TO with the new services, then a dramatiq worker added after them.
reverse() {
  name=reverse; rm -rf "$name"
  aeg "$TO" init "$name" --no-interactive -y --skip-llm-sync -s "$ADD_SERVICES" > "$name.init.log" 2>&1 || { echo "$name: INIT FAILED"; return; }
  ( cd "$name"; [ -d .git ] || git init -q; commit base
    aeg "$TO" add "worker[dramatiq]" -y > "../$name.add.log" 2>&1 || { echo "$name: ADD FAILED"; exit; }
    verdict "$name" )
}

# Project names use hyphens: aegis turns underscores into hyphens.
# Two waves of five: ten template clones at once get connections reset.
run base "" "" > base.result 2>&1 &
run everything "database,scheduler,worker,redis,htmx" "auth[org],ai[sqlite],insights,payment,blog,comms,documents,finance" > everything.result 2>&1 &
run htmx-auth "htmx,database" "auth" > htmx-auth.result 2>&1 &
run finance-pg "database[postgres],scheduler" "auth,finance" > finance-pg.result 2>&1 &
run worker-ai "worker,redis" "ai" > worker-ai.result 2>&1 &
wait
run w-taskiq "worker[taskiq]" "" > w-taskiq.result 2>&1 &
run w-dramatiq "worker[dramatiq]" "" > w-dramatiq.result 2>&1 &
run htmx-org "htmx,database" "auth[org]" > htmx-org.result 2>&1 &
if [ -n "${ADD_SERVICES:-}" ]; then
  run removed "" "" remove > removed.result 2>&1 &
  reverse > reverse.result 2>&1 &
fi
wait; cat ./*.result
