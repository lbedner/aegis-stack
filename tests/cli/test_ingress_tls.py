"""Turning TLS on for a name, the step ``ingress-enable`` and provisioning share.

TLS is rendered into Traefik's static config and the prod compose labels at
generation time, so a project generated without it has no ``:443`` listener
and no certificate resolver for a provisioned name to use.
"""

from pathlib import Path

from aegis.commands.ingress import enable_tls
from aegis.core.copier_manager import load_copier_answers
from tests.cli.conftest import ProjectFactory

EMAIL = "ops@example.org"


def _prod_compose(project: Path) -> str:
    return (project / "docker-compose.prod.yml").read_text()


def test_tls_is_turned_on_for_the_name(project_factory: ProjectFactory) -> None:
    project = project_factory(components=("ingress",))

    enable_tls(project, "203-0-113-7.sslip.io", EMAIL)

    answers = load_copier_answers(project)
    assert answers["ingress_tls"] is True
    assert answers["ingress_domain"] == "203-0-113-7.sslip.io"
    traefik = (project / "traefik" / "traefik.yml").read_text()
    assert "websecure" in traefik and EMAIL in traefik
    assert "Host(`203-0-113-7.sslip.io`)" in _prod_compose(project)
    assert '"443:443"' in _prod_compose(project)


def test_a_new_name_replaces_the_old_one(project_factory: ProjectFactory) -> None:
    """A re-provisioned server has a new IP, so a new sslip.io name."""
    project = project_factory(components=("ingress",))
    enable_tls(project, "203-0-113-7.sslip.io", EMAIL)

    enable_tls(project, "198-51-100-4.sslip.io", EMAIL)

    assert "Host(`198-51-100-4.sslip.io`)" in _prod_compose(project)
    assert "203-0-113-7" not in _prod_compose(project)
    assert load_copier_answers(project)["ingress_domain"] == "198-51-100-4.sslip.io"
