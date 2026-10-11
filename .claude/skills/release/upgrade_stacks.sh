#!/bin/bash
# Upgrade-path check across stack shapes: init each stack at FROM, `update` to
# TO, then count conflict markers / .rej files and run `make check`.
# ADD / ADD_SERVICES (comma lists) then run `aegis add` / `add-service` on each
# updated stack, so components new in the release are also tested on projects
# made before it.
# usage: FROM=0.14.0 TO=0.15.0rc1 [INDEX=testpypi|pypi] [ADD=mcp] [ADD_SERVICES=research] upgrade_stacks.sh <workdir>
: "${FROM:?set FROM}" "${TO:?set TO}"
work=${1:?workdir}; mkdir -p "$work"; cd "$work"
I=()
[ "${INDEX:-testpypi}" = testpypi ] && I=(--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ --index-strategy unsafe-best-match)

run() {
  name=$1; comps=$2; svcs=$3
  rm -rf "$name"
  args=(init "$name" --no-interactive -y --skip-llm-sync)
  [ -n "$comps" ] && args+=(-c "$comps"); [ -n "$svcs" ] && args+=(-s "$svcs")
  uvx --refresh "${I[@]}" "aegis-stack@$FROM" "${args[@]}" > "$name.init.log" 2>&1 || { echo "$name: INIT FAILED"; return; }
  [ -d "$name" ] || { echo "$name: NO PROJECT DIR"; return; }
  ( cd "$name"
    [ -d .git ] || git init -q; git add -A; git commit -qm base --no-verify >/dev/null 2>&1
    uvx "${I[@]}" "aegis-stack@$TO" update -y > "../$name.update.log" 2>&1 || { echo "$name: UPDATE FAILED"; exit; }
    [ -n "${ADD:-}" ] && { uvx "${I[@]}" "aegis-stack@$TO" add "$ADD" -y > "../$name.add.log" 2>&1 || { echo "$name: ADD FAILED"; exit; }; }
    [ -n "${ADD_SERVICES:-}" ] && { uvx "${I[@]}" "aegis-stack@$TO" add-service "$ADD_SERVICES" -y > "../$name.add-service.log" 2>&1 || { echo "$name: ADD-SERVICE FAILED"; exit; }; }
    markers=$(grep -rlE '^(<<<<<<<|>>>>>>>)( |$)' --exclude-dir=.venv --exclude-dir=.git . | wc -l | tr -d ' ')
    rej=$(find . -name '*.rej' -not -path './.venv/*' | wc -l | tr -d ' ')
    make check > "../$name.check.log" 2>&1; rc=$?
    echo "$name: markers=$markers rej=$rej check_exit=$rc $(grep -E '[0-9]+ (passed|failed)' "../$name.check.log" | tail -1)" )
}

# Project names use hyphens: aegis turns underscores into hyphens.
run base "" "" > base.result 2>&1 &
run everything "database,scheduler,worker,redis,htmx" "auth[org],ai[sqlite],insights,payment,blog,comms,documents,finance" > everything.result 2>&1 &
run htmx-auth "htmx,database" "auth" > htmx-auth.result 2>&1 &
run finance-pg "database[postgres],scheduler" "auth,finance" > finance-pg.result 2>&1 &
run worker-ai "worker,redis" "ai" > worker-ai.result 2>&1 &
wait; cat ./*.result
