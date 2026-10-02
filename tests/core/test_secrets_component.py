"""The secrets component: the encrypted database backend behind
``app.core.secrets``, the way the storage component sits behind
``app.core.storage``. It needs the database, takes a backend axis
(``secrets[database]``, the only value today), and owns one table in its
own Postgres schema."""

from aegis.constants import AnswerKeys, ComponentNames
from aegis.core.components import COMPONENTS, ComponentType, component_option_answers
from aegis.core.migration_generator import get_services_needing_migrations
from aegis.core.option_spec import parse_options
from aegis.core.template_generator import TemplateGenerator


def test_secrets_is_an_infrastructure_component_on_the_database() -> None:
    spec = COMPONENTS[ComponentNames.SECRETS]
    assert spec.type is ComponentType.INFRASTRUCTURE
    assert ComponentNames.DATABASE in spec.requires
    assert spec.marker_path == "app/components/secrets/store.py"
    assert "app/components/secrets" in spec.files.primary


def test_the_backend_axis_defaults_to_the_database() -> None:
    spec = COMPONENTS[ComponentNames.SECRETS]
    assert parse_options("secrets", spec) == {"backend": "database"}
    assert component_option_answers("secrets[database]") == {
        AnswerKeys.SECRETS_BACKEND: "database"
    }


def test_its_table_lives_in_its_own_schema() -> None:
    (migration,) = COMPONENTS[ComponentNames.SECRETS].migrations
    assert migration.service_name == "secrets"
    assert migration.schema == "secrets"
    assert migration.stamp_signature == ("table", "secrets.secret")


def test_selecting_it_pulls_in_the_database() -> None:
    from aegis.core.dependency_resolver import DependencyResolver

    resolved = DependencyResolver.resolve_dependencies(["secrets"])
    assert ComponentNames.DATABASE in resolved


def test_the_context_carries_it_and_its_migration() -> None:
    context = TemplateGenerator("demo", ["database", "secrets"]).get_template_context()
    assert context[AnswerKeys.SECRETS] == "yes"
    assert context[AnswerKeys.SECRETS_BACKEND] == "database"
    assert "secrets" in get_services_needing_migrations(context)


def test_without_it_there_is_no_migration() -> None:
    context = TemplateGenerator("demo", ["database"]).get_template_context()
    assert context[AnswerKeys.SECRETS] == "no"
    assert "secrets" not in get_services_needing_migrations(context)
