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
