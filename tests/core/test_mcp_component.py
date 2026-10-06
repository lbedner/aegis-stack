"""The mcp component's record of MCP activity (MCP-09).

Every call an outside assistant makes is kept, by client, in the
component's own table, only where there is a database to keep it in:
without one the record is a log line and the server works the same.
"""

from __future__ import annotations

from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader

from aegis.constants import AnswerKeys, ComponentNames
from aegis.core.component_files import get_template_path
from aegis.core.components import COMPONENTS
from aegis.core.template_generator import TemplateGenerator


def test_the_component_declares_its_activity_migration_and_files() -> None:
    from aegis.core.migration_generator import MCP_MIGRATION

    spec = COMPONENTS[ComponentNames.MCP]
    assert MCP_MIGRATION in spec.migrations
    activity = spec.files.extras[AnswerKeys.DATABASE]
    assert "app/components/mcp/models/calls.py" in activity
    assert "app/components/mcp/activity.py" in activity


@pytest.mark.parametrize(("database", "migrated"), [(True, True), (False, False)])
def test_the_activity_table_is_migrated_only_with_a_database(
    database: bool, migrated: bool
) -> None:
    from aegis.core.migration_generator import get_services_needing_migrations

    components = ["database", "mcp"] if database else ["mcp"]
    context = TemplateGenerator("demo", components).get_template_context()

    assert ("mcp" in get_services_needing_migrations(context)) is migrated


@pytest.mark.parametrize(("database", "kept"), [("yes", True), ("no", False)])
def test_init_keeps_the_activity_files_only_with_a_database(
    tmp_path: Any, database: str, kept: bool
) -> None:
    from aegis.core.post_gen_tasks import cleanup_components

    paths = [
        tmp_path / p
        for p in COMPONENTS[ComponentNames.MCP].files.extras[AnswerKeys.DATABASE]
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# stub\n")
    context = TemplateGenerator(
        "demo", ["database", "mcp"] if database == "yes" else ["mcp"]
    ).get_template_context()

    cleanup_components(tmp_path, context)

    assert all(path.exists() is kept for path in paths)


def test_its_activity_lives_in_its_own_schema() -> None:
    from aegis.core.migration_generator import MCP_MIGRATION

    assert MCP_MIGRATION.schema == "mcp"
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    template = env.get_template(
        "{{ project_slug }}/app/components/mcp/models/calls.py.jinja"
    )
    assert '"schema": "mcp"' in template.render(database_engine="postgres")
    assert "schema" not in template.render(database_engine="sqlite").split('"""')[-1]


TOKEN_FILES = (
    "app/components/mcp/models/tokens.py",
    "app/components/mcp/tokens.py",
    "app/components/mcp/http.py",
    "app/components/backend/api/mcp_tokens.py",
    "app/cli/mcp_tokens_cli.py",
    "tests/components/test_mcp_tokens.py",
)


def test_tokens_come_with_auth() -> None:
    """A token belongs to a person, so the token files are auth's to bring."""
    by_auth = COMPONENTS[ComponentNames.MCP].files.extras[AnswerKeys.AUTH]
    assert set(TOKEN_FILES) <= set(by_auth)


@pytest.mark.parametrize(("services", "kept"), [(["auth"], True), ([], False)])
def test_init_keeps_the_token_files_only_with_auth(
    tmp_path: Any, services: list[str], kept: bool
) -> None:
    from aegis.core.post_gen_tasks import cleanup_components

    paths = [tmp_path / p for p in TOKEN_FILES]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# stub\n")
    context = TemplateGenerator(
        "demo", ["database", "mcp"], selected_services=services
    ).get_template_context()

    cleanup_components(tmp_path, context)

    assert all(path.exists() is kept for path in paths)
