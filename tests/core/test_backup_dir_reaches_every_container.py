"""DATABASE_BACKUP_DIR reaches every container (aegis-stack#1560).

The scheduler enqueues the database backup; a worker runs it. The variable
was set only in the scheduler's environment list, so on a server the
worker wrote its copies into its own writable layer, and the next deploy
destroyed them. Like STORAGE_ROOT, it lives in the Dockerfile's ENV,
which no compose environment list can replace.
"""

from __future__ import annotations

import yaml

from tests.core.test_observability_oom_renders import _ctx, _render

BACKUP_DIR = "/var/backups/app"


def _stack(**overrides: object) -> dict:
    return _ctx(
        **{
            "include_scheduler": True,
            "include_worker": True,
            "include_redis": True,
            **overrides,
        }
    )


def test_dockerfile_sets_the_backup_dir() -> None:
    assert f"ENV DATABASE_BACKUP_DIR={BACKUP_DIR}" in _render(
        "Dockerfile.jinja", _stack()
    )


def test_no_backup_dir_without_a_backup_job() -> None:
    rendered = _render("Dockerfile.jinja", _stack(include_scheduler=False))
    assert "DATABASE_BACKUP_DIR" not in rendered


def test_every_app_container_mounts_the_backup_volume() -> None:
    compose = yaml.safe_load(_render("docker-compose.yml.jinja", _stack()))
    image = compose["x-app"]["image"]
    for name, service in compose["services"].items():
        if service.get("image") != image:
            continue
        assert f"backup-data:{BACKUP_DIR}" in service.get("volumes", []), name
        for entry in service.get("environment") or []:
            assert not str(entry).startswith("DATABASE_BACKUP_DIR="), (
                f"{name}: a compose environment list carries it to that "
                "service alone; it belongs in the Dockerfile"
            )
