---
name: add-cli-command
description: Use when adding a command to this project's own CLI (the app CLI under app/cli/, not the aegis tool). Covers the command module, Typer registration, the sync-plus-asyncio.run rule, and i18n strings.
---

# Add CLI command

The project ships a Typer CLI under `app/cli/`. A command module exposes a Typer
app that is mounted in the CLI root, so a command is not runnable until it is
both defined and registered.

## When to use

Use when adding a subcommand to this project's CLI.

Do NOT use for HTTP routes (see the `add-api-endpoint` skill) or for background
or scheduled work.

## Files that change

- `app/cli/`: command modules live here; add `<name>.py` exposing a Typer app.
- `app/cli/main.py`: register the command by mounting its Typer app.
- `app/i18n/locales/en.py`: add any user-facing strings as i18n keys (English
  only; other locales are a separate translation pass).

## Procedure

1. Write the failing test first under `tests/cli/`, invoking the command with a
   Typer runner. Confirm it fails for the right reason.
2. Create the command module in `app/cli/` with a Typer app and the command
   functions.
3. Commands that need async are `async def` with plain `await`. NEVER call
   `asyncio.run(...)` inside a command: `app/cli/main.py` runs Typer with
   `standalone_mode=False`, checks `inspect.iscoroutine` on the result, and
   owns the single `asyncio.run`. Exemplar: `app/cli/llm.py:reset`. Most
   existing commands still use the old sync-plus-`asyncio.run` shape; that
   is the majority, not the standard, and it should not be copied.
4. Register the module in `app/cli/main.py` (mount its Typer app under a name).
5. Route user-facing text through i18n keys in `app/i18n/locales/en.py`.
6. Run the gates and fix anything red.

## Gates

- `make check`: lint, typecheck, and test.

## Pitfalls

- A command defined but not registered in `app/cli/main.py` never appears in the
  CLI; registration is what wires it in.
- Calling `asyncio.run(...)` inside a command fights the harness in
  `app/cli/main.py`, which already awaits a returned coroutine. Declare the
  command `async def` and `await` directly.
- Hardcoded user-facing strings bypass i18n; add a key in `en.py` instead.
