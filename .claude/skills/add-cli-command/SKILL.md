---
name: add-cli-command
description: Use when adding a command to the aegis tool CLI (the framework's own `aegis ...` entry point, not a generated project's CLI). Covers Typer registration, the sync-plus-asyncio.run rule, brand help theming, i18n strings, optional guided/interactive wiring, tests, and the CLI reference doc that must change together.
---

# Add CLI command

Adds a new top-level command to the aegis tool's own CLI (`aegis <command>`),
as opposed to a command inside a generated project. Traced from
`aegis/commands/update.py` and its registration in `aegis/__main__.py`.

## When to use

Use when the task is "add a new `aegis <command>`" to the framework's own
CLI surface (the tool that generates and updates projects).

Do NOT use for adding a subcommand to a generated project's CLI
(`app/cli/*.py.jinja` in the template tree) - that is template work with its
own conventions, not this skill. Do NOT use for adding a component or
service (`aegis add <component>` / `aegis add-service <name>`); those already
have dedicated commands and belong to the `add-component` / `add-service`
skills. Do NOT use for a plugin-provided CLI sub-app mounted via
`aegis/core/plugins/discovery.py`; that is a separate, plugin-owned
registration path.

## Files that change

Command implementation and registration:

- `aegis/commands/<name>.py`: the command function, e.g. `<name>_command`
  (see `update_command` in `aegis/commands/update.py` for the shape: Typer
  options via `typer.Option(...)`, `lazy_t(...)` for help strings, `t(...)`
  for runtime messages, `brand.success/warn/error` for status lines).
- `aegis/__main__.py`: import the command function and register it with the
  module-level Typer `app`. The exact registration point is the block of
  `app.command(name="...")(...)` calls after `app.add_typer(plugins_app,
  name="plugins")` - add `app.command(name="<name>")(<name>_command)` there,
  next to the existing entries (`update`, `deploy-init`, `ingress-enable`,
  and so on). This is the single place a new command becomes reachable as
  `aegis <name>`.

Help/UX theming (no new files, just correct usage):

- `aegis/cli/brand.py` is the single source of the CLI palette: `AEGIS_TEAL`
  (`#17CCBF`, typeable tokens and success state), `AEGIS_WARNING` (`#F5A623`,
  amber), `AEGIS_ERROR` (`#E23E3E`, red). Call sites never hardcode colors;
  they call `brand.success(...)`, `brand.warn(...)`, `brand.error(...)`,
  `brand.accent(...)`, `brand.muted(...)` (or the `_text` variants for
  inline composition) to express intent. `brand.apply_help_theme()` themes
  Typer's rich `--help` rendering globally (teal for command names and
  flags, dim for metavars/env-var hints, neutral for prose); it runs once
  at CLI startup and needs no per-command change.

Strings (i18n):

- All user-facing text goes through i18n keys in `aegis/i18n/locales/en.py`
  (the real English string), with the same key stubbed into every other
  locale file for parity. Use `lazy_t("<name>.help_opt_...")` for Typer
  `help=` strings (lazy because locale isn't resolved until the `--lang`
  callback runs) and `t("<name>....")` for runtime echo strings. Follow the
  `<command>.<thing>` naming already used by `update.*` and `common.*` (for
  example `common.help_yes`, `common.help_project_path_full` for options
  shared across commands). See the i18n skill for the full add-a-key
  procedure and locale list; do not attempt real (non-English) translation
  in the same change.

Init-style options (only if the new command takes project-shaping options,
the way `init`/`add`/`add-service` do):

- `aegis/cli/guided.py`: add a `choose_<thing>(...)` method on the
  guided-setup UI class if the command should offer a guided prompt step,
  following the existing `choose_worker_backend()` /
  `choose_database_engine()` pattern (a list of `_Choice(value, label,
  description)` fed to `self._select(...)`, i18n-backed via `_g(...)`).
- `aegis/cli/interactive.py`: add an `interactive_<name>_selection(...)` /
  `interactive_<name>_config(...)` function if the command needs a
  non-guided interactive prompt fallback, following
  `interactive_component_add_selection` / `interactive_ai_service_config`.
- `aegis/cli/validators.py`: input validation for CLI-supplied values
  (project names, component/service name lists) - add a
  `validate_<thing>(...)` here if the new option needs syntactic validation,
  following `validate_project_name`.
- `aegis/cli/validation.py`: shared cross-command checks that are not raw
  input validation, such as `validate_copier_project(target_path,
  command_name)` (confirms the target is a Copier-generated project before
  proceeding). Call this if the new command operates on an existing project
  directory, mirroring how `update_command` and others gate on it.
- Most new commands (a status check, a report, a one-shot action) need
  none of this; skip the whole section if the command takes no
  project-shaping options.

Tests:

- `tests/cli/test_<name>_command.py` (or add to an existing file if the
  command is small): `typer.testing.CliRunner` against `aegis.__main__.app`
  (see `tests/cli/test_utils.py` for `CLI_RUNNER`, timeouts, and
  `run_aegis_command` / `run_cli_help_command` helpers). Cover `--help`
  text, success path, and error path.
- `tests/cli/test_cli_basic.py`: add a `test_<name>_help` case asserting the
  command's help text and options appear, following `test_init_help`.

Docs:

- `docs/cli-reference.md`: add a `### aegis <name>` section in command
  order (matches the registration order in `aegis/__main__.py`), with a
  `**Usage:**` code block and an `**Example Output:**` block, following the
  existing `### aegis update` / `### aegis services` sections. No `mkdocs.yml`
  nav change is needed; this page is already wired under `Reference: CLI
  Reference`.

## Procedure

1. Write the failing test first: `tests/cli/test_<name>_command.py` (or a
   case in `test_cli_basic.py`) asserting `aegis <name> --help` exits 0 and
   shows the expected help text. Confirm it fails because the command
   doesn't exist yet.
2. Add `aegis/commands/<name>.py` with `<name>_command(...) -> None`. Keep
   it a plain sync `def`; if it needs to await anything, call
   `asyncio.run(...)` inside the function body (see Pitfalls - Typer has no
   native async command support).
3. Register it in `aegis/__main__.py`: import the function, add
   `app.command(name="<name>")(<name>_command)` next to the existing
   `app.command(...)` calls.
4. Add the command's i18n keys to `aegis/i18n/locales/en.py` (help strings
   via `lazy_t`, runtime strings via `t`), then stub the same keys into
   every other locale file for parity (see the i18n skill).
5. Use `brand.success/warn/error/accent/muted` for all status output; never
   call `typer.secho` with a raw color inline.
6. If the command takes project-shaping options, wire the guided/interactive
   flows (`aegis/cli/guided.py`, `aegis/cli/interactive.py`) and validation
   (`aegis/cli/validators.py` for input shape, `aegis/cli/validation.py` for
   shared project-state checks like `validate_copier_project`). Skip this
   step for options-free or simple-flag commands.
7. Add or extend the test coverage in `tests/cli/` from step 1, including an
   error-path case.
8. Add the `### aegis <name>` section to `docs/cli-reference.md`.
9. Run the gates below and fix anything red.

## Gates

- `make check` (lint, typecheck, test) must pass.
- A command that touches `aegis init` or project generation also needs
  `make test-stacks`: `make check` no longer generates the stack matrix (CI
  does, in its `generation` jobs).
- `make cli-test` for a manual smoke: runs `python -m aegis --help` and
  confirms the CLI still loads with the new command registered.

## Pitfalls

- Typer has no native async command support in any version: a command
  function must be a sync `def`. If it needs async work, call
  `asyncio.run(...)` from inside the sync function body rather than trying
  to declare the command itself `async def` - Typer will not await it.
- Forgetting the `app.command(name="...")(...)` line in `aegis/__main__.py`
  leaves the command fully implemented but unreachable; `aegis <name>
  --help` fails with "no such command" even though `aegis/commands/<name>.py`
  imports and type-checks cleanly.
- Don't hardcode a color (`typer.secho(msg, fg="red")`) at a call site; use
  `brand.error`/`brand.warn`/`brand.success` so the palette stays defined in
  exactly one place (`aegis/cli/brand.py`) and stays in sync with the
  generated frontend's theme.
- Adding a key to `en.py` only fails `tests/core/test_i18n.py`, which
  requires the same key in every other locale file; stub the key everywhere
  in the same change and leave real translation to the separate
  translator-reviewed pass (see the i18n skill).
- `lazy_t(...)` is for `help=` strings evaluated before the `--lang` option
  is resolved (Typer short-circuits its main callback on `--help`); using
  plain `t(...)` for a help string can render against the wrong locale on a
  fresh process. Use `t(...)` for anything echoed at runtime, after the
  callback has already set the locale.
- A command that takes a `--project-path` and operates on an existing
  project should call `validate_copier_project` (or the equivalent check)
  before doing any work, the way `update_command` does immediately after
  resolving the target path - skipping it lets the command run against a
  directory that was never generated by Copier and fail with a confusing
  downstream error instead of a clear one.
