# Research Service

Outside posts and threads, collected by saved searches. What other people published elsewhere (a story, a discussion, a blog post, the comments under them) that you choose to collect, so you can read, search and measure it later. Sources are plugins; storing, refreshing and reading what they find is this service, the same for every source.

!!! info "Quick Start"
    Generate a project with the research service and a source:

    ```bash
    aegis init my-app --services research
    cd my-app
    # install a source plugin, then:
    my-app research add hn "FastAPI launches" '{"q": "fastapi"}' --threads
    my-app research refresh
    my-app research search "template"
    ```

    `my-app research sources` lists the sources installed; the Hacker News source (`aegis-stack-hackernews`) is the first, and any plugin can add one. Research requires the `database` component. With the `scheduler`, every watch refreshes nightly; without it, a watch runs when you ask.

## What You Get

- **Watches** - a saved search on one source. The query is the source's own shape and the source checks it before it is saved.
- **Items** - one row per outside post, comment or page, from any source: `source` and `external_id` identify it, so a refresh updates the row instead of adding one. The numbers every source has (`score`, `comment_count`) are columns; anything else a source carries is in `data`, checked by that source.
- **Threads** - a watch that reads threads stores the discussion under each find, read from its top even when the search hit a reply. A reply the source no longer returns is marked deleted: its numbers stay, its text and author are cleared.
- **Past finds** - each watch remembers when it last found each item, so search can ask for what a watch finds now or for everything it ever found.
- **Numbers over time** - an item's row holds its latest `score` and `comment_count`; each refresh also keeps that day's in `research_item_snapshot` (one row per item per day, a later run the same day replacing it), so when a thread took off is still there after it settles. An item with neither number, a comment on most sources, keeps no history.
- **Owners** - watches are their owner's, and an owner reads what its watches found (replies only through a watch that reads threads). Items themselves are stored once, since outside posts are public. Without an owner (no auth, the CLI) every watch is in reach.
- **Failures stay local** - a source that times out, or a plugin removed while its watches remain, skips those watches for the run; the rest still refresh. Deleting a watch removes what only it found.
- **Reading** - `GET /api/v1/research/items`, the `research search` command, and three read-only tools for agents and MCP clients: `research_search`, `research_thread` and `research_history`.

## Sources

A source is a plugin that registers itself in its own `app/services/<service>/sources.py`; the research service finds it on disk, like `tools.py` and `scheduled_jobs.py`.

```python
from pydantic import BaseModel

from app.services.research.registry import Source, SourceItem, register_source


class Query(BaseModel):
    q: str


async def search(query: Query) -> list[SourceItem]: ...
async def thread(external_id: str) -> list[SourceItem]: ...


register_source(Source(
    name="hn",
    title="Hacker News",
    query=Query,
    search=search,
    thread=thread,
))
```

`search` turns a watch's query into items; a reply it returns names its thread's top in `root_external_id`. `thread` returns one item with everything under it. A `data` model, when given, checks what an item carries beyond the shared columns.

## API

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/v1/research/sources` | The installed sources |
| `GET` | `/api/v1/research/watches` | The caller's watches |
| `POST` | `/api/v1/research/watches` | Save a watch (`source`, `name`, `query`, `with_threads`) |
| `POST` | `/api/v1/research/watches/{id}/refresh` | Run its search now |
| `DELETE` | `/api/v1/research/watches/{id}` | Remove it and what it found |
| `GET` | `/api/v1/research/items` | Search (`text`, `source`, `kind`, `watch_id`, `current_only`, `limit`) |
| `GET` | `/api/v1/research/items/{id}/thread` | The discussion an item belongs to, top first |
| `GET` | `/api/v1/research/items/{id}/history` | Its numbers a day at a time, oldest first |
