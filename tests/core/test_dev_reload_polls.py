"""Dev hot reload polls instead of waiting for file events.

The dev overlay bind-mounts the project into the webserver, and on Docker
Desktop's file sharing inotify events from host edits arrive late or not
at all. Uvicorn's watcher then misses a change and keeps serving the old
code, which once 500'd a page whose template had been deleted by the same
edit. Polling sees every change; the static asset watcher polls for the
same reason.
"""

from pathlib import Path

import pytest
import yaml
from jinja2 import Environment

PROJECT = (
    Path(__file__).parents[2]
    / "aegis/templates/copier-aegis-project/{{ project_slug }}"
)


@pytest.mark.parametrize("plaid", [False, True])
def test_the_dev_webserver_polls_for_changes(plaid: bool) -> None:
    source = (PROJECT / "docker-compose.dev.yml.jinja").read_text()
    rendered = (
        Environment()
        .from_string(source)
        .render(include_finance=plaid, finance_plaid=plaid, project_slug="app")
    )
    webserver = yaml.safe_load(rendered)["services"]["webserver"]
    assert "WATCHFILES_FORCE_POLLING=true" in webserver["environment"]
