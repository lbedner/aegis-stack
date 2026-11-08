"""The assistant's way onto the web (#1997): a search, and a page read as text.

Both ride what the contact lookup already had - Brave search, keyed and
budgeted, and the guarded fetch that refuses any host off the public
internet - so a tool is a thin door, not a second fetch.
"""

from __future__ import annotations

import httpx
import pytest

from app.core import search
from app.core.cache import CacheService
from app.services.ai.domains.chat import web_tools
from tests._fake_dns import answering, resolving_to

PUBLIC = ["93.184.216.34"]


class TestWebSearch:
    @pytest.mark.asyncio
    async def test_hits_come_back_as_title_url_snippet(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake(query: str, *, limit: int = 5) -> list[search.SearchHit]:
            return [
                search.SearchHit(
                    title="MetLife Stable Value Fund",
                    url="https://example.com/fund",
                    snippet="A stable value option.",
                )
            ]

        monkeypatch.setattr(web_tools, "search", fake)

        result = await web_tools.web_search("MetLife Stable Value Fund")

        assert [hit.model_dump() for hit in result.hits] == [
            {
                "title": "MetLife Stable Value Fund",
                "url": "https://example.com/fund",
                "snippet": "A stable value option.",
            }
        ]

    @pytest.mark.asyncio
    async def test_search_off_says_so_rather_than_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No hits with no explanation reads as "nothing on the web"; off
        is a different answer."""
        monkeypatch.setattr(search.settings, "BRAVE_SEARCH_API_KEY", None)
        monkeypatch.setattr(search, "get_cache", lambda: CacheService())

        result = await web_tools.web_search("anything")

        assert result.hits == []
        assert result.note and "off" in result.note

    @pytest.mark.asyncio
    async def test_a_spent_budget_says_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def spent() -> dict[str, object]:
            return {"enabled": True, "queries_today": 25, "daily_budget": 25}

        async def nothing(query: str, *, limit: int = 5) -> list[search.SearchHit]:
            return []

        monkeypatch.setattr(web_tools, "status", spent)
        monkeypatch.setattr(web_tools, "search", nothing)

        result = await web_tools.web_search("anything")

        assert result.hits == []
        assert result.note and "budget" in result.note


class TestReadPage:
    @pytest.mark.asyncio
    async def test_a_page_is_its_readable_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, PUBLIC)
        answering(
            monkeypatch,
            httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=(
                    "<html><head><title>Fund Facts</title>"
                    "<style>p{color:red}</style></head>"
                    "<body><script>alert(1)</script>"
                    "<h1>Fund   Facts</h1><p>Expense ratio 0.45%.</p>"
                    "<p>Inception &amp; history.</p></body></html>"
                ),
            ),
        )

        result = await web_tools.read_page("https://example.com/fund")

        assert result.title == "Fund Facts"
        assert result.text == "Fund Facts\nExpense ratio 0.45%.\nInception & history."
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_a_long_page_is_cut_and_says_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, PUBLIC)
        answering(
            monkeypatch,
            httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<p>" + "word " * 100 + "</p>",
            ),
        )

        result = await web_tools.read_page("https://example.com/", max_chars=40)

        assert len(result.text) == 40
        assert result.truncated is True

    @pytest.mark.asyncio
    async def test_the_rest_is_read_from_an_offset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asking for more continues where the cut was, never the top again."""
        resolving_to(monkeypatch, PUBLIC)
        answering(
            monkeypatch,
            httpx.Response(
                200, headers={"content-type": "text/html"}, text="<p>abcdef</p>"
            ),
        )

        result = await web_tools.read_page(
            "https://example.com/", max_chars=4, offset=4
        )

        assert (result.text, result.offset, result.truncated) == ("ef", 4, False)

    @pytest.mark.asyncio
    async def test_an_empty_shell_says_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fund page drawn by script arrives as no words at all."""
        resolving_to(monkeypatch, PUBLIC)
        answering(
            monkeypatch,
            httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text='<html><body><div id="app"></div><script src="a.js"></script></body></html>',
            ),
        )

        result = await web_tools.read_page("https://example.com/")

        assert result.text == ""
        assert result.note and "script" in result.note

    @pytest.mark.asyncio
    async def test_a_host_off_the_public_internet_is_an_answer_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, ["169.254.169.254"])
        sent = answering(monkeypatch, httpx.Response(200, text="secret"))

        result = await web_tools.read_page("http://metadata.internal/")

        assert result.error
        assert "secret" not in str(result)
        assert sent == []

    @pytest.mark.asyncio
    async def test_a_file_that_is_not_text_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, PUBLIC)
        answering(
            monkeypatch,
            httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=b"%PDF"
            ),
        )

        result = await web_tools.read_page("https://example.com/a.pdf")

        assert result.error and "application/pdf" in result.error

    @pytest.mark.asyncio
    async def test_a_page_that_is_not_there_says_the_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, PUBLIC)
        answering(monkeypatch, httpx.Response(404, text="gone"))

        result = await web_tools.read_page("https://example.com/missing")

        assert result.error == "HTTP 404"
