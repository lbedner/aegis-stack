# The terminal half of the README hero: a stack made, then started. Run by
# record.sh from an empty directory, with AEGIS_REPO (this checkout, whose
# aegis the typed `uvx aegis-stack` runs) and DEMO_PARENT (the folder that
# holds the aegis-demo stack the Overseer take records) set, and that stack
# stopped and its image built: what `make serve` starts is that one, not the
# fresh copy, and it boots rather than builds.

Output terminal.mp4

Set Shell "bash"
Set FontSize 40
Set Width 2560
Set Height 1440
Set Padding 48
Set TypingSpeed 45ms
Set Framerate 60
# The Overseer's own colours: its card on its page, its teal for the cursor.
Set Theme { "name": "Overseer", "background": "#11151a", "foreground": "#e6e8eb", "cursor": "#17ccbf", "selection": "#2a3038", "black": "#11151a", "red": "#e23e3e", "green": "#17ccbf", "yellow": "#f5a623", "blue": "#7aa2f7", "magenta": "#bb9af7", "cyan": "#7dcfff", "white": "#b8bcc1", "brightBlack": "#5c6370", "brightRed": "#ff6b6b", "brightGreen": "#5ee6da", "brightYellow": "#ffc35c", "brightBlue": "#9ab8ff", "brightMagenta": "#d0b8ff", "brightCyan": "#a8e4ff", "brightWhite": "#ffffff" }

Hide
# A Wait reads the cursor's line, so what the take waits on (the init, the
# boot) is shown through `shown`, which passes its output on holding
# the newline back until the next line comes (the cursor stays on the line
# last printed), through `script` so it keeps a terminal and its colours.
Type `shown() { script -q /dev/null "$@" | awk '{ sub(/\r$/, "") } NR>1 { printf "\r\n" } { printf "%s", $0; fflush() } END { printf "\r\n" }'; }; uvx() { shift; shown uv run -q --project "$AEGIS_REPO" aegis "$@"; }; make() { shown "$(type -P make)" "$@"; }; cd() { if [ "$1" = aegis-demo ]; then builtin cd "$DEMO_PARENT/aegis-demo"; else builtin cd "$@"; fi; }; export COMPOSE_MENU=false; clear`
Enter
Show

Sleep 800ms
Type `uvx aegis-stack init aegis-demo -c worker,scheduler,database,htmx -s "ai[sqlite,openai]" -y`
Sleep 600ms
Enter
# The plan, cut to the install, then cut to the stack ready (its prompt
# back). The install's own line is gone in under a second (uv's progress
# draws over it), so the take waits on the one after it, which holds for
# seconds with the install above it.
Wait@120s /Creating project/
Sleep 1.5s
Hide
Wait@180s /Environment file created/
Show
Sleep 2s
Hide
Wait@180s
Sleep 1s
Show
Sleep 3.5s

# The stack the take records, started where the fresh one would be (the
# hidden `cd` above).
Type "cd aegis-demo && make serve"
Sleep 500ms
Enter
# The build's registry check cut (seconds to many), the take resumes at the
# webserver's first line and runs to its "Uvicorn running", where the
# Overseer take cuts in. The take waits on the reloader line under it
# (Uvicorn's own is drawn over within milliseconds).
Sleep 2s
Hide
Wait@240s /webserver-1/
Show
Wait@120s /Started reloader|Uvicorn running/
Sleep 800ms

# Left running for the take, detached: the attached run stops with the tape.
Hide
Ctrl+C
Wait@120s
Type "make serve-bg"
Enter
Wait@240s
