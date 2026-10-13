"""Each part's facts the generated app reads (its category, its CLI name)
are declared once, on its PluginSpec, and written into the template as
``app/core/parts.py`` by ``make parts``. A spec changed without
regenerating the file fails here."""

from aegis.core import parts
from aegis.core.components import COMPONENTS
from aegis.core.plugins.spec import PartCategory
from aegis.core.services import SERVICES


def test_the_template_file_is_what_the_specs_say() -> None:
    assert parts.TEMPLATE_FILE.read_text() == parts.render(), (
        "app/core/parts.py is stale: run `make parts`"
    )


def test_every_part_is_known_by_its_health_name() -> None:
    """The app names a part by its health check: the redis component is
    the cache, htmx the web frontend, inference Ollama."""
    known = {spec.name: spec.app_name for spec in COMPONENTS.values()}
    assert known["redis"] == "cache"
    assert known["htmx"] == "web_frontend"
    assert known["inference"] == "ollama"
    assert known["worker"] == "worker"


def test_every_first_party_part_has_a_category() -> None:
    """Each in one concern, as Overseer groups them."""
    categories = {
        spec.app_name: spec.category
        for spec in (*COMPONENTS.values(), *SERVICES.values())
    }
    assert categories["backend"] is PartCategory.COMPUTE
    assert categories["cache"] is PartCategory.DATA
    assert categories["ollama"] is PartCategory.AI
    assert categories["deploy"] is PartCategory.STACK
    assert categories["observability"] is PartCategory.PLATFORM
    assert categories["documents"] is PartCategory.DATA
    assert categories["auth"] is PartCategory.APP
