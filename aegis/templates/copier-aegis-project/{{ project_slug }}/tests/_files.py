"""Writing a tree of files for a test: a project, or part of one."""

from pathlib import Path


def write_tree(root: Path, files: dict[str, str]) -> None:
    """Each of ``files`` (its path from ``root``: its text) written, its
    folders made."""
    for name, body in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(body)
