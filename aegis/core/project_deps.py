"""What a generated project installs: its ``[project].dependencies``, the
list its image is built from. A command that changes it (``aegis add``,
``add-service``, a plugin, ``update``) says to rebuild the image, read from
the outcome rather than guessed from each spec: a dependency can come from
``pyproject.toml.jinja`` alone (``secrets`` brings ``cryptography``)."""

import tomllib
from pathlib import Path


def dependencies(project: Path) -> frozenset[str]:
    """The project's dependencies; none when its ``pyproject.toml`` is
    missing or unreadable (nothing to compare is nothing to rebuild for)."""
    try:
        data = tomllib.loads((project / "pyproject.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return frozenset()
    return frozenset(data.get("project", {}).get("dependencies", []))
