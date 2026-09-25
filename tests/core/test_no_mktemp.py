"""No generated code creates a temp file by name alone.

``tempfile.mktemp`` returns a name without creating the file, so another
process can create it first (CodeQL py/insecure-temporary-file). The AI
``record`` command used it for synthesized speech (#1253).
"""

from __future__ import annotations

from pathlib import Path

from aegis.core.component_files import get_template_path


def test_no_template_uses_mktemp() -> None:
    root = Path(get_template_path())
    offenders = sorted(
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".jinja"}
        and "tempfile.mktemp(" in p.read_text(errors="ignore")
    )
    assert not offenders, f"tempfile.mktemp in: {offenders}"
