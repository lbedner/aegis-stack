"""A failed revision must not roll back the ones that already worked.

Regenerating a project over an existing postgres volume collides on a
table the volume still carries. The collision itself is guarded now - a
generated ``create_table`` carries ``if_not_exists`` - but the shape of
the failure mattered on its own: every revision ran inside ONE
transaction, so a late failure discarded the earlier successes, leaving
no ``alembic_version`` row and no tables, which then surfaced as missing
tables at runtime with nothing pointing back at the migration.
"""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _env_py(**overrides: object) -> str:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {**get_copier_defaults(), "project_slug": "demo", **overrides}
    return env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/alembic/env.py.jinja").render(
        context
    )


def test_each_revision_commits_on_its_own() -> None:
    assert '"transaction_per_migration": True' in _env_py(include_database=True)


def test_a_generated_create_table_tolerates_one_that_exists() -> None:
    """The other half: a volume that already has the table."""
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    generator = env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/app/cli/migrate_gen.py.jinja"
    ).render(
        {**get_copier_defaults(), "project_slug": "demo", "include_database": True}
    )

    create_table_branch = generator[generator.index("ops.CreateTableOp") :][:200]
    assert "if_not_exists = True" in create_table_branch
