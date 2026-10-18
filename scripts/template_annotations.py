"""Point a generated stack's ``patterns check`` annotations at the templates
it was generated from, for the conformance job in
``.github/workflows/stack-matrix.yml``. Each ``::warning file=...,line=N``
read from stdin names the template's file (``.jinja`` or not) and its
nearest line with the same text, in its properties and at the start of its
message; anything else passes through.

    python scripts/template_annotations.py <project> <template> < found
"""

import re
import sys
from pathlib import Path

ANNOTATION = re.compile(r"^(::\w+ file=)([^,]+),line=(\d+)(.*)$", re.S)


def located(path: str, line: int, project: Path, template: Path) -> tuple[str, int]:
    """Where ``path``'s ``line`` is in ``template``: its file, and the line
    with the same text nearest it (``line`` itself when none has it)."""
    generated = (project / path).read_text().splitlines()
    text = generated[line - 1].strip() if line <= len(generated) else None
    plain = template / path
    file = plain if plain.exists() else plain.with_name(f"{plain.name}.jinja")
    if not file.exists():
        return str(plain), line
    lines = file.read_text().splitlines()
    same = [n for n, there in enumerate(lines, 1) if there.strip() == text]
    return str(file), min(same, key=lambda n: abs(n - line), default=line)


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
    for row in sys.stdin:
        sys.stdout.write(mapped(row, project, template))
