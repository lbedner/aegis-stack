"""Settings saved in the Overseer (``app.core.saved_settings``).

A ``Settings`` field typed ``Configurable`` is listed apart from the
secrets, shown whole with its default. With a writable store it can be
saved, checked against its type first, and every process applies the saved
value as it starts. ``.env`` still wins and reads as read-only.
"""

import ast
import logging
from pathlib import Path

import pytest

from app.components.backend.startup import saved_overrides
from app.core import boot, saved_settings, secrets
from app.core.config import Settings, settings
from app.core.settings_base import RETIRED_SETTINGS
from tests._secret_settings import FakeStore, settings_at_default, use_store

NAME = "MEMORY_THRESHOLD_PERCENT"


@pytest.fixture(autouse=True)
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    settings_at_default(monkeypatch)
    return use_store(monkeypatch)


async def _row(name: str = NAME) -> secrets.SecretStatus:
    row = await secrets.status_of(name)
    assert row is not None
    return row


async def test_a_configurable_setting_is_listed_with_its_default() -> None:
    row = await _row()
    assert row.setting and not row.secret
    assert (row.owner, row.default, row.source) == ("Health", "90.0", None)


async def test_settings_stay_off_the_secrets_list() -> None:
    assert NAME not in {r.name for r in await secrets.status()}


async def test_a_value_is_checked_against_the_settings_type(store: FakeStore) -> None:
    with pytest.raises(secrets.SecretRejectedError):
        await secrets.put(NAME, "lots", actor="ops")
    assert NAME not in store.values


async def test_a_saved_value_applies_when_the_process_starts() -> None:
    assert await secrets.put(NAME, "75", actor="ops") is None
    assert settings.MEMORY_THRESHOLD_PERCENT == 90.0
    assert await saved_settings.apply_saved() == [NAME]
    assert settings.MEMORY_THRESHOLD_PERCENT == 75.0
    row = await _row()
    assert (row.source, row.hint) == ("database", "75.0")


async def test_the_backend_applies_saved_values_as_it_starts() -> None:
    await secrets.put(NAME, "60", actor="ops")
    await saved_overrides.startup_hook()
    assert settings.MEMORY_THRESHOLD_PERCENT == 60.0


async def test_a_value_in_env_wins_and_is_read_only(
    monkeypatch: pytest.MonkeyPatch, store: FakeStore
) -> None:
    monkeypatch.setattr(saved_settings, "IN_ENV", frozenset({NAME}))
    with pytest.raises(secrets.SecretsReadOnlyError):
        await secrets.put(NAME, "75", actor="ops")
    store.values[NAME] = "75"
    assert await saved_settings.apply_saved() == []
    row = await _row()
    assert (row.source, row.hint) == (secrets.ENV, "90.0")


async def test_a_stored_value_that_no_longer_fits_is_skipped(store: FakeStore) -> None:
    store.values[NAME] = "lots"
    assert await saved_settings.apply_saved() == []
    assert settings.MEMORY_THRESHOLD_PERCENT == 90.0


async def test_a_bool_is_picked_from_its_two_values() -> None:
    assert await secrets.choices("TRAFFIC_MONITOR_ENABLED") == [
        ("True", "True"),
        ("False", "False"),
    ]
    with pytest.raises(secrets.SecretRejectedError):
        await secrets.put("TRAFFIC_MONITOR_ENABLED", "maybe", actor="ops")


async def test_a_timezone_must_be_a_real_one(store: FakeStore) -> None:
    if "SCHEDULER_TIMEZONE" not in type(settings).model_fields:
        pytest.skip("no scheduler in this stack")
    offered = [value for value, _ in await secrets.choices("SCHEDULER_TIMEZONE")]
    assert "Europe/Paris" in offered and offered == sorted(offered)
    with pytest.raises(secrets.SecretRejectedError):
        await secrets.put("SCHEDULER_TIMEZONE", "Mars/Olympus", actor="ops")
    await secrets.put("SCHEDULER_TIMEZONE", "Europe/Paris", actor="ops")
    assert store.values["SCHEDULER_TIMEZONE"] == "Europe/Paris"


async def test_without_a_store_nothing_applies() -> None:
    secrets.set_store(None)
    assert await saved_settings.apply_saved() == []


def _read_at_import(tree: ast.AST) -> set[str]:
    """Every ``settings.X`` read outside a function body: module level, a
    class body, a default argument or a decorator, all evaluated once."""
    found: set[str] = set()

    def visit(node: ast.AST, in_function: bool) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            if not isinstance(node, ast.Lambda):
                for once in [*node.decorator_list, *node.args.defaults]:
                    visit(once, in_function)
            for statement in node.body if isinstance(node.body, list) else [node.body]:
                visit(statement, True)
            return
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "settings"
            and not in_function
        ):
            found.add(node.attr)
        for child in ast.iter_child_nodes(node):
            visit(child, in_function)

    visit(tree, False)
    return found


def test_no_configurable_setting_is_read_at_import() -> None:
    """A saved value is applied as a process starts, after every module is
    imported: a setting copied at import would silently never change."""
    app = Path(__file__).resolve().parents[1] / "app"
    marked = {entry.name for entry in saved_settings.declarations()}
    offenders = {
        f"{name} in {path.relative_to(app.parent)}"
        for path in app.rglob("*.py")
        for name in _read_at_import(ast.parse(path.read_text())) & marked
    }
    assert not offenders, f"Read at import, so not Configurable: {sorted(offenders)}"


def test_every_setting_says_what_it_is() -> None:
    """The Settings page shows it under the name; a blank reads as a dash."""
    blank = [entry.name for entry in saved_settings.declarations() if not entry.label]
    assert not blank, f"Configurable without a description: {blank}"


def test_a_retired_setting_left_in_env_still_boots(tmp_path: Path) -> None:
    """A setting nothing reads any more is gone from ``Settings``; a
    ``.env`` that still sets it starts as before (unknown names are
    refused), the value ignored."""
    env = tmp_path / ".env"
    env.write_text("".join(f"{name}=1\n" for name in RETIRED_SETTINGS))
    Settings(_env_file=env)  # type: ignore[call-arg]
    assert not RETIRED_SETTINGS & set(Settings.model_fields)


async def test_a_saved_log_level_applies_once_the_process_has_booted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Logging is set up before saved settings apply, so applying them sets
    the level again."""
    root = logging.getLogger()
    monkeypatch.setattr(root, "level", logging.INFO)
    monkeypatch.setattr(settings, "LOG_LEVEL", "DEBUG")
    await boot.apply_saved_overrides()
    assert root.level == logging.DEBUG
