"""The conformance job's annotations, pointed at the templates: a generated
stack's ``patterns check`` names its own files, which a pull request on this
repo does not have (``scripts/template_annotations.py``)."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts/template_annotations.py"
STORE = "app/services/notes/store.py"


def _mapped(project: Path, template: Path, annotations: str) -> str:
    run = subprocess.run(
        [sys.executable, SCRIPT, project, template],
        input=annotations,
        capture_output=True,
        text=True,
        check=True,
    )
    return run.stdout


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_a_line_lands_where_its_template_has_the_same_text(tmp_path: Path) -> None:
    project, template = tmp_path / "app", tmp_path / "template"
    _write(project / STORE, "x = 1\nread()\n")
    _write(template / f"{STORE}.jinja", "x = 1\n{% if a %}\nb()\n{% endif %}\nread()\n")
    _write(template / "app/plain.py", "y = 2\n")
    _write(project / "app/plain.py", "y = 2\n")
    out = _mapped(
        project,
        template,
        f"::warning file={STORE},line=2,title=t::{STORE}:2 t: why\n"
        "::warning file=app/plain.py,line=1,title=t::app/plain.py:1 t: why\n"
        "2 new; 0 known\n",
    )
    assert out.splitlines() == [
        f"::warning file={template}/{STORE}.jinja,line=5,title=t::"
        f"{template}/{STORE}.jinja:5 t: why",
        f"::warning file={template}/app/plain.py,line=1,title=t::"
        f"{template}/app/plain.py:1 t: why",
        "2 new; 0 known",
    ]
