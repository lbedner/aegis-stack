"""Traefik routes to its own project's containers, never a neighbour's.

The Docker provider watches the whole daemon. Every generated stack labels
its app with the same router and service names (``webserver``), so on a
machine running two stacks each Traefik merged the other's webserver into
its own service and round-robined requests across projects; unreachable
servers still showed UP, and the retry middleware hid the failures. The
provider is constrained to containers of its own compose project.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
TRAEFIK = ROOT / "aegis/templates/copier-aegis-project/{{ project_slug }}/traefik"
CONSTRAINT = "Label(`com.docker.compose.project`, `{{ project_slug }}`)"


@pytest.mark.parametrize("name", ["traefik.yml.jinja", "traefik.dev.yml.jinja"])
def test_the_docker_provider_sees_only_its_own_project(name: str) -> None:
    config = (TRAEFIK / name).read_text()
    assert "docker:" in config
    assert f'constraints: "{CONSTRAINT}"' in config
