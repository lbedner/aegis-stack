"""Writing a tree of files for a test: a project, or part of one."""

from pathlib import Path
import sys


def forget(*packages: str) -> None:
    """Each of ``packages`` and its submodules dropped from ``sys.modules``,
    so the next import reads them from disk again."""
    for name in [n for n in sys.modules if any(n == p or n.startswith(f"{p}.") for p in packages)]:
        del sys.modules[name]


def write_tree(root: Path, files: dict[str, str]) -> None:
    """Each of ``files`` (its path from ``root``: its text) written, its
    folders made."""
    for name, body in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(body)
