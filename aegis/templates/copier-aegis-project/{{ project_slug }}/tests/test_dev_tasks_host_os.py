"""`make serve` names the machine's OS for the Overseer's Local card: the
container sees only Linux, whatever runs Docker."""

from __future__ import annotations

from pathlib import Path
import platform
import sys

import pytest

from scripts import dev_tasks


@pytest.fixture
def linux(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A Linux machine with an empty home; returns the home."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    ("plat", "expected"),
    [
        ("darwin", ("macOS", "https://apple.com")),
        ("win32", ("Windows", "https://microsoft.com")),
    ],
)
def test_mac_and_windows_by_platform(
    monkeypatch: pytest.MonkeyPatch, plat: str, expected: tuple[str, str]
) -> None:
    monkeypatch.setattr(sys, "platform", plat)
    assert dev_tasks._host_os() == expected


def test_a_linux_distro_names_itself(
    monkeypatch: pytest.MonkeyPatch, linux: Path
) -> None:
    release = {"NAME": "Arch Linux", "HOME_URL": "https://archlinux.org/"}
    monkeypatch.setattr(platform, "freedesktop_os_release", lambda: release)
    assert dev_tasks._host_os() == ("Arch Linux", "https://archlinux.org/")


def test_omarchy_is_arch_set_up_its_own_way(
    monkeypatch: pytest.MonkeyPatch, linux: Path
) -> None:
    """Omarchy keeps Arch's os-release; its own directory gives it away."""
    (linux / ".local/share/omarchy").mkdir(parents=True)
    release = {"NAME": "Arch Linux", "HOME_URL": "https://archlinux.org/"}
    monkeypatch.setattr(platform, "freedesktop_os_release", lambda: release)
    assert dev_tasks._host_os() == ("Omarchy", "https://omarchy.org")


def test_a_linux_without_os_release_is_linux(
    monkeypatch: pytest.MonkeyPatch, linux: Path
) -> None:
    def missing() -> dict[str, str]:
        raise OSError

    monkeypatch.setattr(platform, "freedesktop_os_release", missing)
    assert dev_tasks._host_os() == ("Linux", "https://kernel.org")
