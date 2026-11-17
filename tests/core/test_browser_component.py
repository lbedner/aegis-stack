"""Every Playwright pin names one version: client and server refuse each other otherwise."""

import re

from aegis.constants import ComponentNames
from aegis.core.component_files import get_template_path
from aegis.core.components import COMPONENTS


def _template(name: str) -> str:
    return (get_template_path() / "{{ project_slug }}" / name).read_text()


def test_every_playwright_pin_names_the_same_version() -> None:
    dockerfile = _template("app/components/browser/Dockerfile")
    pins = {
        "spec": re.findall(
            r"playwright==([\d.]+)",
            " ".join(COMPONENTS[ComponentNames.BROWSER].pyproject_deps),
        ),
        "pyproject": re.findall(
            r'"playwright==([\d.]+)"', _template("pyproject.toml.jinja")
        ),
        "image": re.findall(r"mcr\.microsoft\.com/playwright:v([\d.]+)-", dockerfile),
        "cli": re.findall(r"playwright@([\d.]+)", dockerfile),
    }

    assert all(len(found) == 1 for found in pins.values()), pins
    assert len({found[0] for found in pins.values()}) == 1, pins


def test_the_browser_has_room_for_a_meeting() -> None:
    """A live Meet call's tab outgrew 2 GiB, shared with ``/dev/shm``: the
    kernel killed it mid call ("Target crashed"). 4 GiB by default, and an
    operator can give it more (``BROWSER_MEMORY``)."""
    from tests.core._compose import load, render

    browser = load(render("docker-compose.yml.jinja", include_browser=True))[
        "services"
    ]["browser"]
    memory = browser["deploy"]["resources"]["limits"]["memory"]
    found = re.fullmatch(r"\$\{BROWSER_MEMORY:-(\d+)G\}", memory)
    assert found and int(found[1]) >= 4, memory
