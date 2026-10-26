"""Point a generated stack's ``patterns check`` annotations at the templates
it was generated from, for the conformance job in
``.github/workflows/stack-matrix.yml``. Each ``::warning file=...,line=N``
read from stdin names the template's file (``.jinja`` or not) and its
nearest line with the same text, in its properties and at the start of its
message; anything else passes through. With ``--found``, the places
``patterns check`` wrote for her review threads (``PATTERNS_FOUND``) are
pointed at the templates the same way, in place, except that a place whose
text no template line has gets no line: a thread is never placed by guess.

    python scripts/template_annotations.py <project> <template> < found
    python scripts/template_annotations.py <project> <template> --found <json>
"""

import json
import re
import sys
from pathlib import Path

ANNOTATION = re.compile(r"^(::\w+ file=)([^,]+),line=(\d+)(.*)$", re.S)


def matched(
    path: str, line: int, project: Path, template: Path
) -> tuple[str, int | None]:
    """Where ``path``'s ``line`` is in ``template``: its file, and the line
    with the same text nearest it (None when none has it)."""
    generated = (project / path).read_text().splitlines()
    text = generated[line - 1].strip() if line <= len(generated) else None
    plain = template / path
    file = plain if plain.exists() else plain.with_name(f"{plain.name}.jinja")
    if not file.exists():
        return str(plain), None
    lines = file.read_text().splitlines()
    same = [n for n, there in enumerate(lines, 1) if there.strip() == text]
    return str(file), min(same, key=lambda n: abs(n - line), default=None)


def located(path: str, line: int, project: Path, template: Path) -> tuple[str, int]:
    """``matched``, falling back to ``line`` itself: an annotation still
    shows near its finding."""
    file, there = matched(path, line, project, template)
    return file, line if there is None else there


def placed(found: Path, project: Path, template: Path) -> None:
    """The places in ``found`` pointed at ``template``, in place; nothing
    when ``patterns check`` wrote none (it did not finish)."""
    if not found.exists():
        return
    body = json.loads(found.read_text())
    for place in body["found"]:
        place["path"], place["line"] = matched(
            place["path"], place["line"], project, template
        )
    found.write_text(json.dumps(body, indent=2) + "\n")


def mapped(row: str, project: Path, template: Path) -> str:
    """``row`` with its ``file=``, ``line=`` and the message's leading
    ``path:line`` pointed at ``template``."""
    found = ANNOTATION.match(row)
    if not found:
        return row
    head, path, line, rest = found.groups()
    file, there = located(path, int(line), project, template)
    rest = rest.replace(f"::{path}:{line} ", f"::{file}:{there} ", 1)
    return f"{head}{file},line={there}{rest}"


if __name__ == "__main__":
    project, template = map(Path, sys.argv[1:3])
    if sys.argv[3:4] == ["--found"]:
        placed(Path(sys.argv[4]), project, template)
    else:
        for row in sys.stdin:
            sys.stdout.write(mapped(row, project, template))
