"""Vendor VS Code's Material Icon Theme file icons into the template.

Overseer draws each file (the code tree, a knowledge base's files) with
the icon VS Code users know for it. The theme ships its own map of file
names and extensions to icons, so nothing in the app lists types: this
copies that map (``icons.json``, trimmed to files) and the icons it names
(no folders) into ``static/vendor/file-icons/``, served with the app, so
no third-party request is made at runtime.

    uv run python scripts/vendor_file_icons.py

Pinned to ``VERSION``: change it to move to another release.
"""

import io
import json
import shutil
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

VERSION = "5.40.0"
PACKAGE = "material-icon-theme"
TARGET = (
    Path(__file__).resolve().parent.parent
    / "aegis/templates/copier-aegis-project/{{ project_slug }}"
    / "app/components/web_frontend/static/vendor/file-icons"
)


def _package(version: str) -> dict[str, bytes]:
    url = f"https://registry.npmjs.org/{PACKAGE}/-/{PACKAGE}-{version}.tgz"
    with urllib.request.urlopen(url) as response:  # noqa: S310 - fixed https host
        data = response.read()
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        return {
            m.name.removeprefix("package/"): tar.extractfile(m).read()  # type: ignore[union-attr]
            for m in tar.getmembers()
            if m.isfile()
        }


def vendor(version: str = VERSION, target: Path = TARGET) -> int:
    """Write the theme's file icons and their map to ``target``: how many."""
    files = _package(version)
    theme = json.loads(files["dist/material-icons.json"])
    # An icon by its file's name, so the map's values are what is served.
    stem = {
        name: PurePosixPath(icon["iconPath"]).stem
        for name, icon in theme["iconDefinitions"].items()
    }
    plain = stem[theme["file"]]
    names = {k: stem[v] for k, v in theme["fileNames"].items()}
    extensions = {k: stem[v] for k, v in theme["fileExtensions"].items()}
    mapped = {
        "version": version,
        "source": f"https://www.npmjs.com/package/{PACKAGE}",
        "file": plain,
        "fileNames": names,
        "fileExtensions": extensions,
    }
    icons = {plain, *names.values(), *extensions.values()}
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for icon in icons:
        (target / f"{icon}.svg").write_bytes(files[f"icons/{icon}.svg"])
    (target / "LICENSE").write_bytes(files["LICENSE"])
    (target / "icons.json").write_text(
        json.dumps(mapped, indent=0, sort_keys=True) + "\n"
    )
    return len(icons)


if __name__ == "__main__":
    print(f"{vendor()} icons in {TARGET}")
