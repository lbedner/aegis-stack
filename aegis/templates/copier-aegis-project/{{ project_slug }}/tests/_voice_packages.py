"""Whether the in-process voice providers' packages are there, for tests.

No stack installs them, so a test says which way it wants it. Needs no
database, unlike ``_voice_catalog``.
"""

from typing import Any

from app.services.ai.domains.voice import models


def packages_installed(monkeypatch: Any, installed: bool) -> None:
    """The voice's answer to whether a package is there (``models.present``)."""
    monkeypatch.setattr(models, "present", lambda module: installed)
