"""A SQLite database survives ``aegis deploy`` on the server.

Dev bind-mounts the whole project, so ``data/app.db`` is a file on the
developer's disk. On the server nothing mounted ``/code/data``: the database
lived in the container and every deploy (``down`` then ``up --build``)
started an empty one. ``aegis deploy`` already keeps ``data/`` on the server
(rsync excludes it and never deletes it; backups copy it); the app
containers have to read it from there.
"""

from typing import Any

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

DATA_MOUNT = "./data:/code/data"


def _app_services(**answers: Any) -> dict[str, Any]:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {
        **get_copier_defaults(),
        "project_slug": "demo",
        "include_scheduler": True,
        "include_worker": True,
        "include_redis": True,
        **answers,
    }
    rendered = env.get_template("{{ project_slug }}/docker-compose.yml.jinja").render(
        context
    )
    services = yaml.safe_load(rendered)["services"]
    return {
        name: service
        for name, service in services.items()
        if "AEGIS_STACK_TAG" in str(service.get("image", ""))
    }


def test_every_app_container_reads_sqlite_from_the_server_disk() -> None:
    services = _app_services(include_database=True, database_engine="sqlite")

    assert {"webserver", "scheduler"} <= set(services)
    for name, service in services.items():
        assert DATA_MOUNT in service.get("volumes", []), name


@pytest.mark.parametrize(
    "answers",
    [
        {"include_database": True, "database_engine": "postgres"},
        {"include_database": False},
    ],
)
def test_without_sqlite_there_is_nothing_to_mount(answers: dict[str, Any]) -> None:
    for name, service in _app_services(**answers).items():
        assert DATA_MOUNT not in service.get("volumes", []), name
