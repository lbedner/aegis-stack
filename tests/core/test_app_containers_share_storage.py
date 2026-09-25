"""Every container built from the app image mounts the shared object store.

A service's own ``volumes:`` list REPLACES the ``x-app`` anchor's (YAML
merge keys never join lists). The scheduler declared one for its backup
directory and so lost ``storage-data``: every scheduled job ran against a
private, empty ``/data/storage`` (#1251, found in aegis-steward).
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"
STORAGE = "storage-data:/data/storage"


def _compose(**overrides: Any) -> dict[str, Any]:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {
        **get_copier_defaults(),
        "project_slug": "demo",
        "include_worker": True,
        "include_scheduler": True,
        "include_redis": True,
        "include_database": True,
        **overrides,
    }
    rendered = env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/docker-compose.yml.jinja"
    ).render(context)
    return yaml.safe_load(rendered)


def _app_services(compose: dict[str, Any]) -> dict[str, dict[str, Any]]:
    image = compose["x-app"]["image"]
    return {
        name: svc
        for name, svc in compose["services"].items()
        if svc.get("image") == image
    }


@pytest.mark.parametrize(
    "stack",
    [
        {},
        {"scheduler_backend": "sqlite"},
        {"include_database": False},
        {"include_scheduler": False},
    ],
    ids=["default", "persistent-scheduler", "no-database", "no-scheduler"],
)
def test_every_app_container_mounts_the_object_store(stack: dict[str, Any]) -> None:
    services = _app_services(_compose(**stack))

    missing = [
        name for name, svc in services.items() if STORAGE not in svc.get("volumes", [])
    ]
    assert not missing, f"{missing} do not mount {STORAGE}"


@pytest.mark.parametrize(
    "stack",
    [{}, {"include_scheduler": False}, {"include_database": False}],
    ids=["default", "no-scheduler", "no-database"],
)
def test_every_named_volume_a_service_mounts_is_declared(
    stack: dict[str, Any],
) -> None:
    """Moving a mount onto the anchor must not outrun its declaration:
    compose refuses to start on an undeclared named volume."""
    compose = _compose(**stack)
    declared = set(compose.get("volumes") or {})
    for name, svc in compose["services"].items():
        for mount in svc.get("volumes", []):
            source = str(mount).split(":", 1)[0]
            if source.startswith((".", "/")):
                continue
            assert source in declared, f"{name} mounts undeclared volume {source}"
