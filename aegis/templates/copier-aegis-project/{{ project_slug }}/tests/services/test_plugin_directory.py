"""Plugins, as an agent reads them: the ones this stack has (what ``aegis
add`` recorded) and the ones it could add, from the public directory
``aegis plugins search`` reads."""

from collections.abc import Mapping, Sequence

import httpx

from app.core.tools import get_tool
from app.services.system import plugin_directory

CRAWL = {
    "name": "aegis-stack-crawl4ai",
    "install_name": "crawl4ai",
    "install_command": "aegis add crawl4ai",
    "summary": "Crawl web pages for research",
    "latest_version": "0.4.0",
    "latest_release_at": "2026-09-24T23:22:33",
    "verified": True,
    "verified_note": None,
    "aegis_version": "aegis-stack>=0.13.1",
    "downloads": 508,
    "stars": 85561,
    "repository_url": "https://github.com/unclecode/crawl4ai",
    "pypi_url": "https://pypi.org/project/aegis-stack-crawl4ai/",
    "index_label": "PyPI",
    "detail_url": "/plugins/crawl4ai",
    "entry_point": "aegis_stack_crawl4ai.plugin:get_spec",
    "description": None,
    "pulse_url": "https://pulse.aegis-stack.io/search/aegis-stack-crawl4ai",
    "human_downloads_30d": None,
    "badge": "new",  # one the directory adds later: kept, not dropped
}
SCRAPE = CRAWL | {
    "name": "aegis-stack-scrape",
    "install_name": "scrape",
    "install_command": "aegis add scrape",
}


def _directory(
    listed: Sequence[Mapping[str, object]], seen: list[str]
) -> httpx.AsyncClient:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"plugins": list(listed)})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


def test_the_installed_are_what_aegis_add_recorded() -> None:
    found = plugin_directory.installed(
        {
            "_plugins": [
                {"name": "crawl4ai", "version": "0.3.0", "verified": True},
                "legacy>=1.0",  # an old string entry: nothing to say of it
            ]
        }
    )
    assert [(p.name, p.version, p.verified) for p in found] == [
        ("crawl4ai", "0.3.0", True)
    ]


async def test_the_directory_says_what_could_be_added_and_how() -> None:
    seen: list[str] = []
    async with _directory([CRAWL, SCRAPE], seen) as client:
        found, total, note = await plugin_directory.listed(
            "crawl", {"crawl4ai"}, client
        )
    assert note is None and total == 2
    assert seen == [f"{plugin_directory.DIRECTORY_URL}?q=crawl"]
    crawl, scrape = found
    assert crawl.installed and not scrape.installed
    assert scrape.add == "pip install aegis-stack-scrape && aegis add scrape"
    assert crawl.detail_url == "https://aegis-stack.io/plugins/crawl4ai"
    # Everything the directory says of a plugin, for weighing one up.
    assert (crawl.downloads, crawl.stars) == (508, 85561)
    assert crawl.repository_url == "https://github.com/unclecode/crawl4ai"
    assert crawl.more == {"badge": "new"}


async def test_a_long_directory_is_capped_and_counted() -> None:
    many = [CRAWL | {"install_name": f"p{i}"} for i in range(130)]
    async with _directory(many, []) as client:
        found, total, _ = await plugin_directory.listed(None, set(), client, limit=100)
    assert (len(found), total) == (100, 130)


async def test_an_unreachable_directory_is_said_not_raised() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as client:
        found, total, note = await plugin_directory.listed(None, set(), client)
    assert found == () and total == 0
    assert note and "aegis-stack.io" in note


def test_the_tool_is_an_admins_read() -> None:
    tool = get_tool("plugins")
    assert tool is not None
    assert tool.effect == "read" and tool.admin


async def test_a_directory_waking_from_idle_is_asked_again() -> None:
    """Its first answer after a quiet spell can stall; the second comes from
    a site that is up."""
    tries: list[int] = []

    def wakes(request: httpx.Request) -> httpx.Response:
        tries.append(1)
        if len(tries) == 1:
            raise httpx.ReadTimeout("waking", request=request)
        return httpx.Response(200, json={"plugins": [CRAWL]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(wakes)) as client:
        found, total, note = await plugin_directory.listed(None, set(), client)
    assert (len(tries), total, note) == (2, 1, None)
