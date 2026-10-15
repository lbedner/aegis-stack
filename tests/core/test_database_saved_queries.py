"""The database component keeps Query's saved queries in a table of its
own (``app/components/database``): a revision where the stack already
migrates, last, so an existing project's revisions keep their numbers; a
database-only stack, which ships no alembic, makes it with ``create_all``."""

from aegis.constants import ComponentNames
from aegis.core.components import COMPONENTS
from aegis.core.migration_generator import (
    DATABASE_MIGRATION,
    get_services_needing_migrations,
)
from aegis.core.template_generator import TemplateGenerator


def test_a_database_migrates_its_saved_queries_last() -> None:
    context = TemplateGenerator(
        "demo", ["database", "deploy", "mcp"]
    ).get_template_context()
    assert get_services_needing_migrations(context)[-1] == "database"


def test_a_stack_that_migrates_nothing_else_gets_no_revision_for_it() -> None:
    """Database-only stays without migration machinery; no database, no table."""
    for components in ([], ["database"]):
        context = TemplateGenerator("demo", components).get_template_context()
        assert get_services_needing_migrations(context) == []


def test_the_component_declares_its_migration_and_files() -> None:
    spec = COMPONENTS[ComponentNames.DATABASE]
    assert spec.migrations == [DATABASE_MIGRATION]
    assert DATABASE_MIGRATION.stamp_signature == ("table", "saved_query")
    assert "app/components/database" in spec.files.primary
    assert "tests/components/test_database_saved.py" in spec.files.primary
