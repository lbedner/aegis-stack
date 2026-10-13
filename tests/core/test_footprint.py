"""What a project's stack takes, measured on the machine it is built on
(``aegis.core.footprint``): its production services' limits and images,
its data volumes, and what its containers use now. ``docker`` is a fake
answering from canned output; nothing runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegis.core import footprint

MIB = 1024**2
# ``docker compose ... --profile prod config --no-interpolate --format json``
CONFIG = {
    "name": "my-app",
    "services": {
        "webserver": {
            "image": "${AEGIS_STACK_TAG:-my-app:latest}",
            "profiles": ["dev", "prod"],
            "deploy": {"resources": {"limits": {"memory": "768M", "cpus": "2.0"}}},
            "volumes": [{"type": "volume", "source": "app-data", "target": "/data"}],
        },
        "worker-system": {
            "image": "${AEGIS_STACK_TAG:-my-app:latest}",
            "profiles": ["dev", "prod"],
            "deploy": {
                "resources": {
                    "limits": {
                        "memory": "${SYSTEM_WORKER_MEMORY:-1G}",
                        "cpus": "${SYSTEM_WORKER_CPUS:-1.0}",
                    }
                }
            },
        },
        "redis": {"image": "redis:7-alpine"},  # no profile: always, no limit
        "tailwind": {"image": "node:22", "profiles": ["dev"]},
        "test_runner": {"image": "my-app:latest", "profiles": ["test"]},
    },
    "volumes": {"app-data": {"name": "my-app_app-data"}},
}
IMAGES = {"my-app:latest": 1_200_000_000, "redis:7-alpine": 41_000_000}


class FakeDocker:
    """``docker`` with canned answers; records what it was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> str:
        self.asked.append(args)
        if "config" in args:
            return json.dumps(CONFIG)
        if args[:2] == ("image", "inspect"):
            size = IMAGES.get(args[-1])
            if size is None:
                raise footprint.DockerError(f"No such image: {args[-1]}")
            return f"{size}\n"
        if args[:2] == ("system", "df"):
            return json.dumps(
                {"Volumes": [{"Name": "my-app_app-data", "Size": "336.2MB"}]}
            )
        if args[0] == "ps":
            return "my-app-webserver-1\twebserver\nmy-app-tailwind-1\ttailwind\n"
        if args[0] == "stats":
            return (
                "my-app-webserver-1\t385.2MiB / 1.5GiB\n"
                "my-app-tailwind-1\t53.55MiB / 23.43GiB\n"
            )
        raise AssertionError(f"unexpected docker {args}")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text("SYSTEM_WORKER_MEMORY=2G\n")
    return tmp_path


def _by_name(found: dict[str, object]) -> dict[str, dict[str, object]]:
    return {s["name"]: s for s in found["services"]}  # type: ignore[index, union-attr]


def test_only_the_services_production_runs(root: Path) -> None:
    found = _by_name(footprint.measure(root, FakeDocker()))
    assert sorted(found) == ["redis", "webserver", "worker-system"]


def test_each_services_limits_as_a_deploy_resolves_them(root: Path) -> None:
    """``${VAR:-default}`` from the env file a deploy ships (``.env.deploy``
    over ``.env``), else its default; no limit is None."""
    (root / ".env.deploy").write_text("SYSTEM_WORKER_MEMORY=512M\n")
    found = _by_name(footprint.measure(root, FakeDocker()))
    assert (found["webserver"]["memory"], found["webserver"]["cpus"]) == (
        768 * MIB,
        2.0,
    )
    assert (found["worker-system"]["memory"], found["worker-system"]["cpus"]) == (
        512 * MIB,
        1.0,
    )
    assert (found["redis"]["memory"], found["redis"]["cpus"]) == (None, None)


def test_images_volumes_and_what_runs_now(root: Path) -> None:
    measured = footprint.measure(root, FakeDocker())
    found = _by_name(measured)
    assert found["webserver"]["image_size"] == 1_200_000_000
    assert found["redis"]["image_size"] == 41_000_000
    assert measured["volumes"] == [{"name": "app-data", "size": 336_200_000}]
    assert found["webserver"]["used"] == round(385.2 * MIB)
    assert found["worker-system"]["used"] is None  # not running here
    assert measured["images"] == 1_241_000_000  # each image once


def test_an_image_not_built_here_counts_nothing(root: Path) -> None:
    docker = FakeDocker()
    IMAGES.pop("redis:7-alpine")
    try:
        found = _by_name(footprint.measure(root, docker))
    finally:
        IMAGES["redis:7-alpine"] = 41_000_000
    assert found["redis"]["image_size"] is None


def test_the_compose_files_a_deploy_uses() -> None:
    docker = FakeDocker()
    footprint.measure(Path("."), docker)
    (config,) = [a for a in docker.asked if "config" in a]
    assert config[:5] == (
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.prod.yml",
    )
    assert "--no-interpolate" in config  # DOMAIN is required only at deploy


@pytest.mark.parametrize(
    ("text", "size"),
    [
        ("768M", 768 * MIB),  # compose's units are binary
        ("1G", 1024 * MIB),
        ("128m", 128 * MIB),
        ("385.2MiB", round(385.2 * MIB)),
        ("336.2MB", 336_200_000),  # docker system df's are decimal
        ("0B", 0),
        ("12kB", 12_000),
    ],
)
def test_sizes_as_docker_and_compose_write_them(text: str, size: int) -> None:
    assert footprint.size_of(text) == size
