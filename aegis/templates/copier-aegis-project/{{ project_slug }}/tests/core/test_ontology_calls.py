"""What each services folder's code talks to (``ontology.calls``), read
from what is already there: its imports (a component, a core client that
says which component it fronts, another service) and the secrets it
declares that what is enabled needs now (an outside provider). Each a
node's id in the system model."""

from pathlib import Path

import pytest

from app.core import source_index
from app.core.ontology import calls
from app.core.secrets import Secret
from tests._files import write_tree


def _package(root: Path, *imports: str) -> Path:
    """A services folder whose one module makes ``imports``."""
    write_tree(
        root, {"fake/__init__.py": "", "fake/client.py": "\n".join(imports) + "\n"}
    )
    return root / "fake"


def test_a_service_talks_to_what_it_imports(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        "from app.core.cache import get_cache",  # fronts the Cache
        "from app.components.inference.client import OllamaClient",  # Ollama's
        "from app.components.backend.api import router",  # it runs in it
        "from app.services.blog.models import Post",
        "import app.services.system.health",  # the stack's own code
        "from app.core.log import logger",  # fronts nothing
    )
    assert calls.talks_to(package, (), source_index.at(tmp_path)) == [
        "component:cache",
        "component:ollama",
        "service:blog",
    ]


def test_a_service_using_the_worker_hands_work_to_its_queue(tmp_path: Path) -> None:
    """Nothing calls the worker: work is enqueued, and the worker takes it."""
    package = _package(tmp_path, "from app.components.worker.pools import enqueue_task")
    assert calls.talks_to(package, (), source_index.at(tmp_path)) == ["component:queue"]


def test_a_service_talks_to_the_providers_whose_keys_it_needs(
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
    assert calls.talks_to(package, secrets, source_index.at(tmp_path)) == [
        "external:OpenAI",
        "external:Stripe",
        "external:Twilio",
    ]


def test_each_outside_provider_names_the_keys_it_is_called_with() -> None:
    """What the map checks are set: the needed keys behind each provider."""
    assert all(names for names in calls.provider_keys().values())


def test_a_provider_switched_is_the_one_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read live, not kept: switching provider in settings redraws."""
    needed = {"value": True}
    entry = Secret(
        "K",
        owner="Fake (Stripe)",
        needed=lambda: needed["value"],
        module="app.services.fake.x",
    )
    monkeypatch.setattr(calls.secrets, "declared", lambda: (entry,))
    assert calls.provider_keys() == {"Stripe": ["K"]}
    needed["value"] = False
    assert calls.provider_keys() == {}
