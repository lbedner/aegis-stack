"""The dev stack's deploy-agent image, which installs the aegis this project
pins from PyPI when it builds."""

from tests.core._compose import load, render


def test_its_install_is_reported_to_pypi_as_automation() -> None:
    """PyPI counts a download as CI when the installer saw ``CI``,
    ``BUILD_ID``, ``BUILD_BUILDID`` or ``PIP_IS_CI`` (pip and uv read the
    same four). A Docker build sets none of them, so the image's install
    would count as a person's."""
    compose = load(
        render("docker-compose.dev.yml.jinja", include_deploy=True, include_redis=True)
    )
    lines = compose["services"]["deploy-agent"]["build"]["dockerfile_inline"].split(
        "\n"
    )

    install = next(i for i, line in enumerate(lines) if "aegis-stack" in line)
    assert "ENV PIP_IS_CI=1" in lines[:install]
