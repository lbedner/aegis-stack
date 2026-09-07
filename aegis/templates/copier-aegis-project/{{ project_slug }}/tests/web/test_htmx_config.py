"""htmx runtime configuration as the browser receives it.

Read back from the ``htmx-config`` meta tag on a real page and evaluated
the way htmx does (first ``responseHandling`` rule whose ``code`` regex
matches the status wins), so these pin behaviour, not a JSON string.
"""

import json
import re
from typing import Any

from fastapi.testclient import TestClient
import pytest

from tests.web.dom import one, select


@pytest.fixture
def page(client: TestClient) -> str:
    return client.get("/").text


@pytest.fixture
def config(page: str) -> dict[str, Any]:
    return json.loads(one(page, 'meta[name="htmx-config"]').get("content") or "")


def rule_for(config: dict[str, Any], status: int) -> dict[str, Any]:
    """The rule htmx would apply to ``status`` (``RegExp.test`` semantics)."""
    for rule in config["responseHandling"]:
        if re.search(rule["code"], str(status)):
            return rule
    raise AssertionError(f"no responseHandling rule matches {status}")


class TestResponseHandling:
    def test_validation_errors_swap(self, config: dict[str, Any]) -> None:
        """Pattern 1: a 422 carries the re-rendered form and must land."""
        assert rule_for(config, 422)["swap"] is True

    def test_success_swaps(self, config: dict[str, Any]) -> None:
        assert rule_for(config, 200)["swap"] is True

    def test_no_content_does_not_swap(self, config: dict[str, Any]) -> None:
        assert rule_for(config, 204)["swap"] is False

    def test_server_errors_do_not_swap_and_raise_the_error_event(
        self, config: dict[str, Any]
    ) -> None:
        """A 500 body is a traceback page, never content; the global
        ``htmx:responseError`` listener turns it into a toast instead."""
        rule = rule_for(config, 500)
        assert rule["swap"] is False
        assert rule.get("error") is True

    def test_other_client_errors_do_not_swap(self, config: dict[str, Any]) -> None:
        assert rule_for(config, 404)["swap"] is False


class TestHistory:
    def test_snapshots_stay_disabled(self, config: dict[str, Any]) -> None:
        """Restoring an Alpine-expanded DOM duplicates the page; a history
        miss must be a clean full load instead."""
        assert config["historyCacheSize"] == 0
        assert config["refreshOnHistoryMiss"] is True


class TestExtensions:
    def test_sse_extension_loads_after_htmx_core(self, page: str) -> None:
        """Pattern 5 needs ``hx-ext="sse"``; the extension registers itself
        against a global htmx must already have defined."""
        srcs = [s.get("src") or "" for s in select(page, "head script[src]")]
        core = next(i for i, s in enumerate(srcs) if "htmx.org@" in s)
        sse = next(i for i, s in enumerate(srcs) if "htmx-ext-sse@" in s)
        assert core < sse
