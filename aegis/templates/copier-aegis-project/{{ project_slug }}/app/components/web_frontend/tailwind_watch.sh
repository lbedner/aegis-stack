#!/bin/sh
# Keep the dev Tailwind watcher rebuilding.
#
# `tailwindcss --watch` can stop rebuilding while its process stays up, and
# then new classes never reach app.css with nothing on screen. Docker does
# not restart an unhealthy container, so this restarts the watcher itself:
# when it exits, and when a source changed, appeared or was deleted and no
# build followed by the next check (it polls every second, so a healthy
# watcher has rebuilt by then).
#
# A build is the "Done in <n>ms." line Tailwind prints after every one, not
# app.css's mtime: Tailwind skips writing an unchanged app.css, so an edit
# that adds no class leaves it older than the template on a healthy watcher.
set -u

ROOT=${TAILWIND_ROOT:-/code}
# The local binary, not npx: npx runs Tailwind as a child of its own, and a
# restart that kills only npx leaves the stuck watcher running beside the new.
TAILWIND=${TAILWIND_BIN:-$ROOT/node_modules/.bin/tailwindcss}
CHECK=${TAILWIND_CHECK_SECONDS:-15}
WEB="$ROOT/app/components/web_frontend"
IN="$WEB/static/input.css"
OUT="$WEB/static/dist/app.css"
SOURCES="$WEB/templates $WEB/static/js $IN $ROOT/tailwind.config.js"

BUILT=$(mktemp)
LISTED=$(mktemp)
FIFO=$(mktemp -u)
mkfifo "$FIFO"
pid=""
trap 'if [ -n "$pid" ]; then kill "$pid" 2>/dev/null; fi; rm -f "$BUILT" "$LISTED" "$FIFO"; exit 0' TERM INT

sources() {
    # shellcheck disable=SC2086  # SOURCES is a list of paths
    find $SOURCES -type f 2>/dev/null | sort
}

unbuilt() {
    # shellcheck disable=SC2086
    newer=$(find $SOURCES -type f -newer "$BUILT" 2>/dev/null | head -n 1)
    if [ -n "$newer" ]; then
        echo "$newer"
    elif ! sources | cmp -s - "$LISTED"; then
        # A deleted file is never newer than the build; the list catches it.
        echo "a deleted source"
    fi
}

while true; do
    while IFS= read -r line; do
        printf '%s\n' "$line"
        case $line in *"Done in "*) touch "$BUILT"; sources >"$LISTED" ;; esac
    done <"$FIFO" &
    $TAILWIND -i "$IN" -o "$OUT" --watch=always --poll >"$FIFO" 2>&1 &
    pid=$!
    seen=""
    while kill -0 "$pid" 2>/dev/null; do
        sleep "$CHECK" &
        wait $!
        now=$(unbuilt)
        if [ -n "$now" ] && [ "$now" = "$seen" ]; then
            echo "tailwind-watch: $now changed and was not rebuilt; restarting the watcher" >&2
            # KILL, not TERM: a hung process can sit on TERM indefinitely.
            kill -9 "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
            break
        fi
        seen=$now
    done
    echo "tailwind-watch: the watcher stopped; restarting it" >&2
    sleep 1 &
    wait $!
done
