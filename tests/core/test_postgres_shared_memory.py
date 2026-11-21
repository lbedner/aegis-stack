"""Postgres gets more than Docker's 64 MB ``/dev/shm``.

Parallel workers (parallel index vacuum, hash and sort workers) allocate
their shared memory there, and fail with "could not resize shared memory
segment ... No space left on device" once a segment outgrows it (#2020).
``/dev/shm`` counts against the container's memory, so it stays inside the
service's limit.
"""

from aegis.core.footprint import size_of
from tests.core._compose import load, render


def test_postgres_shared_memory_is_past_the_default_and_inside_its_limit() -> None:
    compose = load(render("docker-compose.yml.jinja", database_engine="postgres"))
    postgres = compose["services"]["postgres"]
    limit = postgres["deploy"]["resources"]["limits"]["memory"]

    assert 64 * 2**20 < size_of(postgres["shm_size"]) < size_of(limit)
