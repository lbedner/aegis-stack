"""STORAGE_ROOT reaches every container.

The compose anchor's ``environment`` list is replaced, not merged, by a
service that declares its own (YAML merge keys join mappings, never
lists); four services do, so a value put only on the anchor never
reached them and object storage fell back to the code directory inside
every container. The Dockerfile's ENV is what every container sees.
"""

from __future__ import annotations

import yaml

from tests.core.test_observability_oom_renders import _ctx, _render


def test_dockerfile_sets_the_storage_root() -> None:
    assert "ENV STORAGE_ROOT=/data/storage" in _render("Dockerfile.jinja", _ctx())


def test_compose_does_not_rely_on_the_anchor_for_it() -> None:
    """Every service that overrides the anchor's environment still sees
    the storage root, because nothing in compose is expected to carry it."""
    compose = yaml.safe_load(_render("docker-compose.yml.jinja", _ctx()))
    for name, service in compose["services"].items():
        for entry in service.get("environment") or []:
            assert not str(entry).startswith("STORAGE_ROOT="), (
                f"{name}: STORAGE_ROOT in a compose environment list is lost by "
                "any service that declares its own; it belongs in the Dockerfile"
            )
