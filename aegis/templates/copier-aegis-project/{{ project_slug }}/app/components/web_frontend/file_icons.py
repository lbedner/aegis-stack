"""Each file's icon, as VS Code's Material Icon Theme draws it, by the
theme's own map of file names and extensions (``static/vendor/file-icons``,
vendored by the framework's ``scripts/vendor_file_icons.py``), read once:
nothing here lists file types."""

from functools import cache
import json
from pathlib import PurePosixPath
from typing import Any, NamedTuple

from .assets import STATIC_DIR

FOLDER = "vendor/file-icons"


class FileIcon(NamedTuple):
    kind: str  # the theme's name for it: python, docker, file
    url: str  # served as is: not fingerprinted, so no manifest to ask


@cache
def _theme() -> dict[str, Any]:
    return json.loads((STATIC_DIR / FOLDER / "icons.json").read_text())


def icon_for(path: str) -> FileIcon:
    """The icon for ``path``: by its whole name (``Dockerfile``,
    ``pyproject.toml``), then its longest extension the theme knows
    (``d.ts`` before ``ts``), else the theme's plain file."""
    theme = _theme()
    name = PurePosixPath(path).name.lower()
    parts = name.split(".")[1:]
    extensions = (".".join(parts[n:]) for n in range(len(parts)))
    known = (theme["fileExtensions"].get(e) for e in extensions)
    kind = theme["fileNames"].get(name) or next(
        (icon for icon in known if icon), theme["file"]
    )
    return FileIcon(kind, f"/static/{FOLDER}/{kind}.svg")
