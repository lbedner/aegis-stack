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
from aegis.core.component_files import get_copier_defaults, get_template_path
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
    # The HTTP app's lifespan, run by the backend's hooks (not main.py).
    "app/components/backend/startup/mcp_lifespan.py",
    "app/components/backend/shutdown/mcp_lifespan.py",
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


def test_run_code_comes_with_ai() -> None:
    by_ai = COMPONENTS[ComponentNames.MCP].files.extras[AnswerKeys.AI]
    assert "app/components/mcp/run_code.py" in by_ai


def _granted(**answers: Any) -> str:
    """The rendered ``MCP_TOOLS`` line for these answers."""
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {
        **get_copier_defaults(),
        "project_slug": "demo",
        "include_mcp": True,
        **answers,
    }
    config = env.get_template("{{ project_slug }}/app/core/config.py.jinja").render(
        context
    )
    return next(row for row in config.splitlines() if "MCP_TOOLS:" in row)


@pytest.mark.parametrize("finance", [True, False])
def test_every_stack_grants_the_overseer_reads(finance: bool) -> None:
    """MCP never starts empty: what is wrong, what broke and what led up to
    it are on every stack, finance or not."""
    line = _granted(include_finance=finance)

    assert all(f'"{name}"' in line for name in ("health", "errors", "logs"))
    assert ('"ledger"' in line) is finance


@pytest.mark.parametrize("finance", [True, False])
@pytest.mark.parametrize(
    ("answers", "granted"),
    [
        (
            {"include_ai": True, "ai_framework": "pydantic-ai", "ai_backend": "sqlite"},
            True,
        ),
        (
            {"include_ai": True, "ai_framework": "pydantic-ai", "ai_backend": "memory"},
            False,
        ),
        (
            {"include_ai": True, "ai_framework": "langchain", "ai_backend": "sqlite"},
            False,
        ),
        ({"include_ai": False}, False),
    ],
)
def test_run_code_is_granted_by_default_only_where_it_can_run(
    answers: dict[str, Any], granted: bool, finance: bool
) -> None:
    """The sandbox is the AI service's code mode: pydantic-ai, kept agents.
    It chains the Overseer reads, so it needs no finance."""
    line = _granted(include_finance=finance, **answers)

    assert ('"run_code"' in line) is granted


def _lifespan(**answers: Any) -> str:
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())), keep_trailing_newline=True
    )
    context = {**get_copier_defaults(), "project_slug": "demo", **answers}
    rendered = env.get_template(
        "{{ project_slug }}/app/integrations/main.py.jinja"
    ).render(context)
    start = rendered.index("async def lifespan(")
    return rendered[start : rendered.index("\ndef ", start)]


def test_mcp_leaves_the_lifespan_alone() -> None:
    """``aegis add mcp`` merges against the installed template rendered with
    the project's old answers, so a gate near the lifespan's ``yield``
    conflicts on projects made by one version or another (0.15.0 shipped
    without the blank line before it). MCP's lifespan runs from its own
    startup and shutdown hooks instead, and the lifespan renders the same
    with MCP on or off."""
    off = _lifespan(include_auth=True, include_mcp=False)

    assert _lifespan(include_auth=True, include_mcp=True) == off
    assert "\n\n    yield\n" in off


@pytest.mark.parametrize(
    ("auth", "label"),
    [
        (False, "Outside assistants, over stdio"),
        (True, "Outside assistants, over stdio and HTTP"),
    ],
)
def test_its_subtitle_names_the_transports_it_is_served_over(
    auth: bool, label: str
) -> None:
    """HTTP is served only with auth (each token is someone's)."""
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())), keep_trailing_newline=True
    )
    context = {
        **get_copier_defaults(),
        "project_slug": "demo",
        "include_mcp": True,
        "include_auth": auth,
    }
    rendered = env.get_template(
        "{{ project_slug }}/app/services/system/ui.py.jinja"
    ).render(context)

    assert f'ComponentName.MCP: "{label}",' in rendered
