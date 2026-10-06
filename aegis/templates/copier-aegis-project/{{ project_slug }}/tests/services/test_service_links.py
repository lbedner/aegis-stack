"""What each service talks to (``service_links``), read from what is
already there: its imports (a component, a core client that says which
component it fronts, another service) and the secrets it declares that
what is enabled reads (an outside provider)."""

from pathlib import Path

from app.core.secrets import Secret
from app.services.system import service_links


def _package(root: Path, *imports: str) -> Path:
    """A service package whose one module makes ``imports``."""
    package = root / "fake"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "client.py").write_text("\n".join(imports) + "\n")
    return package


def test_a_service_talks_to_what_it_imports(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        "from app.core.cache import get_cache",  # fronts the Cache
        "from app.components.inference.client import OllamaClient",
        "from app.components.backend.api import router",  # it runs in it
        "from app.services.blog.models import Post",
        "import app.services.system.health",  # every service's plumbing
        "from app.core.log import logger",  # fronts nothing
    )
    assert service_links.talks_to(package, ()) == [
        "cache",
        "inference",
        "service_blog",
    ]


def test_a_service_talks_to_the_providers_whose_keys_it_reads(
    tmp_path: Path,
) -> None:
    """The secrets it declares, the ones what is enabled needs: by the
    provider an owner names in brackets, the owner itself, or, where the
    owner is the service, its label's."""
    package = _package(tmp_path)
    module = "app.services.fake.providers"
    secrets = (
        Secret("A", owner="Fake (Stripe)", needed=True, module=module),
        Secret("B", owner="Twilio", needed=True, module=module),
        Secret("C", owner="Fake", label="OpenAI API key", needed=True, module=module),
        Secret("D", owner="Resend", needed=False, module=module),
        Secret("E", owner="Elsewhere", needed=True, module="app.services.other"),
    )
    assert service_links.talks_to(package, secrets) == [
        "outside:OpenAI",
        "outside:Stripe",
        "outside:Twilio",
    ]


def test_every_installed_service_but_the_plumbing_is_read() -> None:
    """Each by its registry key; System and Shared, which every service
    imports to be one, are not services anyone uses."""
    found = service_links.links()
    assert found and all(key.startswith("service_") for key in found)
    assert not {"service_system", "service_shared"} & set(found)


def test_each_outside_provider_names_the_keys_it_is_called_with() -> None:
    """What the map checks are set: the needed keys behind each provider."""
    found = service_links.provider_keys()
    assert all(key.startswith(service_links.OUTSIDE) for key in found)
    assert all(names for names in found.values())
