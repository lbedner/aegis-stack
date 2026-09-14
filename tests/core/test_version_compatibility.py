"""The version gate must not go quiet when it cannot read a version.

A project stamped ``_template_version: HEAD`` parses to nothing, so
``check_version_compatibility`` returns UNKNOWN - which
``validate_version_compatibility`` used to fall off the end of, silently.
That project is then never told its CLI and template have diverged, across
a major version included (aegis-stack#1136).
"""

from pathlib import Path

import pytest

from aegis.core.version_compatibility import (
    VersionCompatibility,
    check_version_compatibility,
    validate_version_compatibility,
)


def test_unparseable_template_version_is_unknown() -> None:
    assert check_version_compatibility("0.11.1", "HEAD") == VersionCompatibility.UNKNOWN


def test_unknown_warns_and_does_not_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import aegis.core.version_compatibility as vc

    monkeypatch.setattr(vc, "get_cli_version", lambda: "0.11.1")
    monkeypatch.setattr(vc, "get_project_template_version", lambda path: "HEAD")

    validate_version_compatibility(tmp_path, command_name="add")

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "HEAD" in output, "unreadable template version passed silently"
