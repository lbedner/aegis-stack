"""A project gets alembic exactly when something in it ships a migration.

``pyproject.toml.jinja`` decides from the answers alone (update renders see
nothing else), so it keeps its own copy of the rule
``get_services_needing_migrations`` owns. That copy had drifted: a stack
whose only table came from the secrets component, or deploy history, got a
migration and no alembic to run it, and ``migrate_gen`` failed at init.
"""

from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path
from aegis.core.migration_generator import get_services_needing_migrations

STACKS: dict[str, dict[str, Any]] = {
    "database only": {"include_database": True},
    "secrets": {"include_database": True, "include_secrets": True},
    "deploy with a database": {"include_database": True, "include_deploy": True},
    "deploy without a database": {"include_deploy": True},
    "scheduler on sqlite": {
        "include_database": True,
        "include_scheduler": True,
        "scheduler_backend": "sqlite",
    },
    "scheduler in memory": {"include_scheduler": True},
    "auth": {"include_database": True, "include_auth": True},
    "ai in memory": {"include_ai": True, "ai_backend": "memory"},
    "ai on sqlite": {
        "include_database": True,
        "include_ai": True,
        "ai_backend": "sqlite",
    },
    "finance": {"include_database": True, "include_finance": True},
}


def _pyproject(answers: dict[str, Any]) -> str:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {**get_copier_defaults(), "project_slug": "demo", **answers}
    return env.get_template("{{ project_slug }}/pyproject.toml.jinja").render(context)


@pytest.mark.parametrize("stack", STACKS)
def test_alembic_ships_exactly_when_a_migration_does(stack: str) -> None:
    answers = STACKS[stack]
    migrates = bool(get_services_needing_migrations(answers))

    assert ('"alembic==' in _pyproject(answers)) is migrates


@pytest.mark.parametrize("stack", ["secrets", "deploy with a database", "finance"])
def test_update_generates_the_migrations_of_every_table_owner(
    stack: str, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``aegis update`` kept its own list and never wrote these revisions."""
    import aegis.commands.update as upd

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        upd,
        "generate_missing_migrations",
        lambda path, answers: seen.setdefault("gen", []),
    )
    monkeypatch.setattr(
        upd,
        "run_post_generation_tasks",
        lambda path, **kwargs: seen.update(kwargs) or True,
    )

    upd._run_postgen(tmp_path, STACKS[stack])

    assert "gen" in seen
    assert seen["include_migrations"] is True


def _database_init(answers: dict[str, Any]) -> str:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {
        **get_copier_defaults(),
        "project_slug": "demo",
        "database_engine": "postgres",
        **answers,
    }
    name = "{{ project_slug }}/app/components/backend/startup/database_init.py.jinja"
    return env.get_template(name).render(context)


@pytest.mark.parametrize(
    "stack", [s for s in STACKS if STACKS[s].get("include_database")]
)
def test_postgres_startup_migrates_exactly_when_a_migration_ships(stack: str) -> None:
    """Startup keeps the same rule, to choose alembic over ``create_all``: on
    a deploy-only Postgres stack ``create_all`` met a ``deploy`` schema the
    missing migration never created."""
    answers = STACKS[stack]
    migrates = bool(get_services_needing_migrations(answers))

    assert (
        "def _check_and_stamp_existing_tables" in _database_init(answers)
    ) is migrates
