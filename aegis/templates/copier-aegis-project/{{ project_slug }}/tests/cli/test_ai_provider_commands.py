"""The provider commands run at all: ``ai providers``, ``ai add-provider``
and ``ai use-provider`` import their helpers inside the command body, so a
wrong import path only fails when someone types the command. All three
once reached for ``app.cli.services`` (a relative import one level short)
and died before doing anything."""

import ast
from pathlib import Path

import pytest

from app.cli.ai import providers as providers_cli
from tests._cli import invoke

MODULE = Path(providers_cli.__file__)


def test_ai_providers_prints_the_table() -> None:
    result = invoke(["ai", "providers"])
    assert result.exit_code == 0, result.output
    assert "Anthropic" in result.output


def test_every_command_import_resolves() -> None:
    """Each function-local ``from ... import`` in the module names a real
    module, checked without running commands that write to ``.env``."""
    import importlib

    tree = ast.parse(MODULE.read_text())
    package = providers_cli.__package__
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            name = ("." * node.level) + node.module
            importlib.import_module(name, package=package if node.level else None)


def test_add_provider_saves_the_key_to_the_secrets_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a writable store the key goes there (checked, audited, live),
    not into .env."""
    from app.core import secrets
    from app.services.ai.domains.llm import provider_management
    from tests._probe import answering
    from tests._secret_settings import secret_settings

    saved: dict[str, str] = {}

    class Store:
        name = "database"
        writable = True

        async def get(self, name: str) -> str | None:
            return saved.get(name)

        async def get_many(self, names: list[str]) -> dict[str, str | None]:
            return {n: saved.get(n) for n in names}

        async def put(
            self, name: str, value: str, hint: str | None, actor: str
        ) -> None:
            saved[name] = value

        async def delete(self, name: str, actor: str) -> None:
            saved.pop(name, None)

        async def stored(self) -> dict[str, secrets.StoredSecret]:
            return {}

    def refuse_env(updates: dict[str, str], env_path: object = None) -> None:
        raise AssertionError(f".env must not be written: {sorted(updates)}")

    monkeypatch.setattr(provider_management, "update_env_file", refuse_env)
    monkeypatch.setattr(
        provider_management, "get_existing_api_key", lambda *a, **k: None
    )
    monkeypatch.setattr(provider_management, "get_missing_dependency", lambda p: None)
    answering(monkeypatch, 200)
    with secret_settings("OPENAI_API_KEY"):
        secrets.set_store(Store())
        result = invoke(
            ["ai", "add-provider", "openai", "--no-set-default"],
            input="sk-test-0123456789abcdef\n",
        )
    secrets.set_store(None)
    assert result.exit_code == 0, result.output
    assert saved == {"OPENAI_API_KEY": "sk-test-0123456789abcdef"}
    assert "sk-test-0123456789abcdef" not in result.output
