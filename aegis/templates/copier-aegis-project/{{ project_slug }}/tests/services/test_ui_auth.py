"""Delete confirmations say what the delete does.

The user and organization deletes are soft: the row keeps ``deleted_at``
and ``POST .../restore`` brings it back. The Flet dialogs said "Permanently
delete '<email>'? This cannot be undone." - the opposite of what happens -
while the web Overseer worded the same action correctly. One wording, here,
for every frontend.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from app.services.system import ui_auth

PROMISES_PERMANENCE = ("permanent", "cannot be undone")


def _says_permanent(text: str) -> bool:
    return any(word in text.lower() for word in PROMISES_PERMANENCE)


def test_deleting_a_user_is_described_as_what_it_does() -> None:
    title, body = ui_auth.delete_user_confirmation("ada@example.com")

    assert "ada@example.com" in body
    assert "sign in" in body
    assert not _says_permanent(title + body)


def test_deleting_an_org_says_which_part_is_gone_for_good() -> None:
    """The org row is restorable; its memberships and invites are not."""
    title, body = ui_auth.delete_org_confirmation("Acme")

    assert "Acme" in body
    assert "member" in body.lower()
    assert "permanently delete" not in (title + body).lower()


def _confirm_message(
    module: str, cls: str, handler: str, record: dict[str, Any], monkeypatch: Any
) -> str:
    tab_module = importlib.import_module(module)
    shown: dict[str, Any] = {}

    class Recorder:
        def __init__(self, **kwargs: Any) -> None:
            shown.update(kwargs)

        def show(self) -> None:
            pass

    monkeypatch.setattr(tab_module, "ConfirmDialog", Recorder)
    tab_cls = getattr(tab_module, cls)
    monkeypatch.setattr(tab_cls, "page", property(lambda self: object()))
    getattr(object.__new__(tab_cls), handler)(record)
    return shown["message"]


def test_the_dashboard_user_dialog_uses_that_wording(monkeypatch: Any) -> None:
    pytest.importorskip("flet")
    message = _confirm_message(
        "app.components.frontend.dashboard.modals.auth_users_tab",
        "AuthUsersTab",
        "_on_delete_user",
        {"id": 7, "email": "ada@example.com"},
        monkeypatch,
    )
    assert message == ui_auth.delete_user_confirmation("ada@example.com")[1]


def test_the_dashboard_org_dialog_uses_that_wording(monkeypatch: Any) -> None:
    pytest.importorskip("app.components.frontend.dashboard.modals.auth_orgs_tab")
    message = _confirm_message(
        "app.components.frontend.dashboard.modals.auth_orgs_tab",
        "AuthOrgsTab",
        "_on_delete_org",
        {"id": 3, "name": "Acme"},
        monkeypatch,
    )
    assert message == ui_auth.delete_org_confirmation("Acme")[1]


CHROME_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)


@pytest.mark.parametrize(
    ("agent", "label"),
    [
        (CHROME_MAC, "Chrome 154 · macOS"),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120.0 Safari/537.36 Edg/120.0",
            "Edge 120 · Windows",
        ),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
            " AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0"
            " Mobile/15E148 Safari/604.1",
            "Safari 17 · iOS",
        ),
        (
            "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36",
            "Chrome 120 · Android",
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Firefox 121 · Linux",
        ),
        ("python-httpx/0.28.1", "python-httpx 0.28.1"),  # a script, by name
        ("Some device", "Some device"),
        (None, "Unknown device"),
    ],
)
def test_a_device_reads_as_its_browser_and_system(
    agent: str | None, label: str
) -> None:
    """A browser's whole user-agent string is a line too long to read: its
    browser and version and the system it runs on say which device it is."""
    assert ui_auth.device_label(agent) == label


def test_signing_a_device_out_names_it_as_the_table_does() -> None:
    title, body = ui_auth.revoke_session_confirmation(CHROME_MAC)
    assert title == "Sign out this device"
    assert "Chrome 154 · macOS" in body and "Mozilla" not in body
    assert "this device" in ui_auth.revoke_session_confirmation(None)[1]
