"""The dev object store answers only to the app's own credentials.

With no identity configured SeaweedFS treats every request as anonymous:
any key is accepted, and ListBuckets returns nothing, because an
anonymous caller owns no buckets. Handing it the app's ``S3_ACCESS_KEY``
and ``S3_SECRET_KEY`` as its admin identity closes the store to other
keys and lets the Overseer list every bucket. With auth on, ``/`` answers
403, so the healthcheck probes ``/healthz``.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
COMPOSE = (
    ROOT
    / "aegis/templates/copier-aegis-project/{{ project_slug }}/docker-compose.yml.jinja"
)


def _service(name: str) -> str:
    text = COMPOSE.read_text()
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \S|\Z)", text, re.M | re.S)
    assert match, f"no {name} service in {COMPOSE.name}"
    return match.group(1)


def test_seaweedfs_takes_the_apps_credentials_as_its_identity() -> None:
    service = _service("seaweedfs")
    assert "AWS_ACCESS_KEY_ID=${S3_ACCESS_KEY" in service
    assert "AWS_SECRET_ACCESS_KEY=${S3_SECRET_KEY" in service


def test_the_healthcheck_survives_auth() -> None:
    probe = re.search(r"test: \[(.*)\]", _service("seaweedfs"))
    assert probe and "/healthz" in probe.group(1)
