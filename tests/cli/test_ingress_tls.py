"""Turning TLS on for a name, the step ``ingress-enable`` and provisioning share.

TLS is rendered into Traefik's static config and the prod compose labels at
generation time, so a project generated without it has no ``:443`` listener
and no certificate resolver for a provisioned name to use.
"""

from pathlib import Path

import yaml

from aegis.commands.deploy import DEPLOY_CONFIG_FILE
from aegis.commands.ingress import ACME_PLACEHOLDER, enable_tls
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
    assert "websecure" in traefik and f"email: {ACME_PLACEHOLDER}" in traefik
    assert "Host(`203-0-113-7.sslip.io`)" in _prod_compose(project)
    assert '"443:443"' in _prod_compose(project)


def test_the_certificates_email_is_never_committed(
    project_factory: ProjectFactory,
) -> None:
    """A public repository would publish it: it waits in the git-ignored
    ``.aegis/deploy.yml``, which each deploy stamps into the server's .env
    as ACME_EMAIL, and Traefik's config is filled from that at start."""
    project = project_factory(components=("ingress",))

    enable_tls(project, "203-0-113-7.sslip.io", EMAIL)

    assert EMAIL not in (project / "traefik" / "traefik.yml").read_text()
    assert EMAIL not in (project / ".copier-answers.yml").read_text()
    config = yaml.safe_load((project / DEPLOY_CONFIG_FILE).read_text())
    assert config["acme_email"] == EMAIL
    assert ACME_PLACEHOLDER in _prod_compose(project)  # filled at start


def test_a_new_name_replaces_the_old_one(project_factory: ProjectFactory) -> None:
    """A re-provisioned server has a new IP, so a new sslip.io name."""
    project = project_factory(components=("ingress",))
    enable_tls(project, "203-0-113-7.sslip.io", EMAIL)

    enable_tls(project, "198-51-100-4.sslip.io", EMAIL)

    assert "Host(`198-51-100-4.sslip.io`)" in _prod_compose(project)
    assert "203-0-113-7" not in _prod_compose(project)
    assert load_copier_answers(project)["ingress_domain"] == "198-51-100-4.sslip.io"
