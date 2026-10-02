"""A generated project names its own CLI, never ``my-app``.

The CLI is installed under the project's slug, but hints in the dashboard and
the CLI's own help said ``my-app api-load-test run ...``, ``my-app insights
collect ...``: every project showed a command that does not exist there.
``aegis-stack init my-app`` stays allowed: there ``my-app`` is a sample
project name the reader chooses, not this project's command.
"""

from __future__ import annotations

import re

from aegis.core.component_files import get_template_path

APP = get_template_path() / "{{ project_slug }}" / "app"
HARDCODED = re.compile(r"(?<![\w/-])my-app [a-z]")
SAMPLE_NAME = re.compile(r"init my-app\b")


def test_no_command_is_spelled_with_a_fixed_project_name() -> None:
    offenders = [
        f"{path.relative_to(APP)}:{n}"
        for path in sorted(APP.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".jinja", ".html"}
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if HARDCODED.search(SAMPLE_NAME.sub("", line))
    ]
    assert offenders == [], f"hardcoded 'my-app' CLI name: {offenders}"
