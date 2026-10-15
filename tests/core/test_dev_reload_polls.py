"""Dev hot reload polls instead of waiting for file events.

The dev overlay bind-mounts the project into the webserver, and on Docker
Desktop's file sharing inotify events from host edits arrive late or not
at all. Uvicorn's watcher then misses a change and keeps serving the old
code, which once 500'd a page whose template had been deleted by the same
edit. Polling sees every change; the static asset watcher polls for the
same reason.
"""

import pytest

from tests.core._compose import load, render


@pytest.mark.parametrize("plaid", [False, True])
def test_the_dev_webserver_polls_for_changes(plaid: bool) -> None:
    rendered = render(
        "docker-compose.dev.yml.jinja", include_finance=plaid, finance_plaid=plaid
    )
    webserver = load(rendered)["services"]["webserver"]
    assert "WATCHFILES_FORCE_POLLING=true" in webserver["environment"]
