# Browser

A Chromium the app drives remotely, in its own container: pages that need JavaScript, sign-ins, a bot that joins a meeting. The container runs Playwright's browser server; the app ships only the Playwright client (its Node driver included), so the browsers and their system libraries never enter the app image.

```bash
aegis add browser
```

## What you get

- **A `browser` service** in the compose stack, built from the official `mcr.microsoft.com/playwright` image with Playwright's CLI baked in, running `playwright run-server` on port 3000 with a 2 GB `/dev/shm` (Chromium crashes without it).
- **Settings:** `BROWSER_URL` (default `ws://browser:3000/`, the compose service). From the host, `make serve` publishes the server on a free port and the app reaches it on localhost there.
- **The client:** `app.components.browser.client.connect()`, an async context manager that opens a browser in the container and closes it on exit.
- **A health check:** the component shows in the Overseer as up or down, with the endpoint and the client version.

## Using it

```python
from app.components.browser.client import connect

async with connect() as browser:
    page = await browser.new_page()
    await page.goto("https://example.com")
    title = await page.title()
```

Launch flags travel with each connection, so every caller picks its own:

```python
# A meeting bot wants fake media devices; a crawler does not.
async with connect(["--use-fake-ui-for-media-stream"]) as browser:
    ...
```

Each `connect()` launches its own browser in the container. Several can run at once; each one costs memory in the container, so the service is capped at 2 GB.

## Versions

The client and the server speak one protocol version. The `playwright` pin in `pyproject.toml` and the image tag and CLI version in `app/components/browser/Dockerfile` all name the same release; upgrade them together.
