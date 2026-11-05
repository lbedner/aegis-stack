"""The Overseer half of the README hero, recorded by Playwright: the
Overview, Resources, the Scheduler, the Database and its tables, then a
question to Illiana on a fresh conversation and her answer's wiring opened
larger.

Captured from Chrome's own screencast (each frame as Chrome paints it, with
its timestamp) rather than Playwright's video, which is low-bitrate and
skips frames; ffmpeg turns the frames into a steady 60fps H.264. The page
is zoomed to about 156%, and a drawn cursor glides to what it clicks, since a
headless browser draws none.

Writes ``overseer.mp4`` and ``marks.txt`` (when each shot starts, in seconds
from the first frame) to the output directory, for the stitch to label.

    uv run --with playwright python demos/hero/overseer.py http://127.0.0.1:8001 out/
"""

import asyncio
import base64
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import CDPSession, Locator, Page, async_playwright

# 1232x693 CSS pixels is a 1920x1080 window zoomed to about 156% (125% on
# 125%), so the page reads at a README's width; rendered at 2560 wide, so
# text stays sharp.
VIEWPORT = {"width": 1232, "height": 693}
OUT_WIDTH, OUT_HEIGHT = 2560, 1440
SCALE = OUT_WIDTH / VIEWPORT["width"]
FPS = 60
QUESTION = "Show me the wiring of the AI service."
HOLD = 1500

# A pointer drawn in the page: follows mousemove, pulses on mousedown, and
# keeps its place across a full page load.
CURSOR = """
(() => {
  const draw = () => {
    if (document.getElementById('hero-cursor')) return;
    const c = document.createElement('div');
    c.id = 'hero-cursor';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2l16 9-7 2-3 7z" fill="#fff" stroke="#000" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position: 'fixed', left: '0', top: '0', zIndex: 2147483647,
      pointerEvents: 'none', transform: 'translate(-3px,-2px)', transition: 'none'});
    const at = JSON.parse(sessionStorage.getItem('hero-cursor') || '[768,432]');
    c.style.left = at[0] + 'px'; c.style.top = at[1] + 'px';
    document.documentElement.appendChild(c);
    addEventListener('mousemove', e => {
      c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px';
      sessionStorage.setItem('hero-cursor', JSON.stringify([e.clientX, e.clientY]));
    }, true);
    addEventListener('mousedown', e => {
      const p = document.createElement('div');
      Object.assign(p.style, {position: 'fixed', left: e.clientX - 14 + 'px', top: e.clientY - 14 + 'px',
        width: '28px', height: '28px', borderRadius: '50%', border: '2px solid #17CCBF',
        zIndex: 2147483646, pointerEvents: 'none', transition: 'transform .45s, opacity .45s'});
      document.documentElement.appendChild(p);
      requestAnimationFrame(() => { p.style.transform = 'scale(1.8)'; p.style.opacity = '0'; });
      setTimeout(() => p.remove(), 500);
    }, true);
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', draw); else draw();
})();
"""


class Screencast:
    """Chrome's painted frames, each with when it was painted."""

    def __init__(self, cdp: CDPSession, frames: Path) -> None:
        self.cdp, self.frames = cdp, frames
        self.times: list[float] = []
        self.stopped = 0.0
        cdp.on("Page.screencastFrame", self._frame)

    def _frame(self, event: dict) -> None:
        path = self.frames / f"{len(self.times):06d}.jpg"
        path.write_bytes(base64.b64decode(event["data"]))
        self.times.append(event["metadata"]["timestamp"])
        asyncio.ensure_future(
            self.cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
        )

    async def start(self) -> None:
        await self.cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 92,
                "maxWidth": OUT_WIDTH,
                "maxHeight": OUT_HEIGHT,
            },
        )

    async def stop(self) -> None:
        await self.cdp.send("Page.stopScreencast")
        self.stopped = time.time()

    def since_start(self) -> float:
        """Seconds into the video: a frame's timestamp is wall-clock time,
        and a still screen paints none, so the last frame can lag."""
        return time.time() - self.times[0] if self.times else 0.0

    def encode(self, out: Path) -> None:
        """Each frame held until the next one, the last until the cast
        stopped (a still screen paints none), resampled to ``FPS``."""
        listing = self.frames / "frames.txt"
        lines = []
        for i, at in enumerate(self.times):
            until = self.times[i + 1] if i + 1 < len(self.times) else self.stopped
            hold = until - at
            lines += [f"file '{i:06d}.jpg'", f"duration {max(hold, 1 / FPS):.4f}"]
        lines.append(f"file '{len(self.times) - 1:06d}.jpg'")
        listing.write_text("\n".join(lines) + "\n")
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-vf",
                f"fps={FPS},scale={OUT_WIDTH}:{OUT_HEIGHT}:flags=lanczos,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                "16",
                "-movflags",
                "faststart",
                # concat holds the repeated last image as long again
                "-t",
                f"{self.stopped - self.times[0]:.3f}",
                str(out),
            ],
            check=True,
        )


class Pointer:
    """The mouse, moved the way a hand moves it: eased, over a moment."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.x, self.y = VIEWPORT["width"] / 2, VIEWPORT["height"] / 2

    async def glide(self, x: float, y: float, seconds: float = 0.7) -> None:
        steps = max(int(seconds * FPS), 1)
        x0, y0 = self.x, self.y
        for step in range(1, steps + 1):
            t = step / steps
            ease = 0.5 - math.cos(math.pi * t) / 2
            await self.page.mouse.move(x0 + (x - x0) * ease, y0 + (y - y0) * ease)
            await self.page.wait_for_timeout(1000 / FPS)
        self.x, self.y = x, y

    async def click(self, target: Locator, seconds: float = 0.7) -> None:
        await target.scroll_into_view_if_needed()
        box = await target.bounding_box()
        if box is None:
            raise RuntimeError(f"nothing to click: {target}")
        # The middle of what is on screen: a log line runs past the window's
        # edge, so its own middle can be off it.
        right = min(box["x"] + box["width"], VIEWPORT["width"])
        await self.glide((box["x"] + right) / 2, box["y"] + box["height"] / 2, seconds)
        await self.page.wait_for_timeout(250)
        await self.page.mouse.click(self.x, self.y)


async def center(page: Page, selector: str) -> None:
    """Scroll what ``selector`` finds to the middle of the screen, smoothly."""
    await page.evaluate(
        "s => document.querySelector(s)?.scrollIntoView({behavior: 'smooth', block: 'center'})",
        selector,
    )
    await page.wait_for_timeout(900)


async def overview(page: Page, url: str) -> None:
    """Where Overseer opens: every part of the stack at a glance. Loaded
    before the cast starts, so the take opens on it, not a blank page; the
    chat set to a fresh conversation there too, so Illiana opens on none."""
    await page.goto(f"{url}/overseer")
    await page.wait_for_load_state("networkidle")
    await page.locator("#chat-fab").click()
    await page.locator("#chat-drawer-body #chat-thread").wait_for(state="attached")
    await page.get_by_role("button", name="New conversation").click()
    await page.wait_for_function(
        "() => !document.querySelector('#chat-thread [data-role]')"
    )
    # Closed, not reloaded: the thread stays as it is across the pages.
    await page.evaluate(
        "() => { Alpine.$data(document.querySelector('[x-data^=chatDrawer]')).open = false }"
    )
    await page.locator("#chat-fab").wait_for()


async def visit(page: Page, pointer: Pointer, target: Locator) -> None:
    """A page opened from a link, held once it has settled."""
    await pointer.click(target)
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(HOLD)


async def resources(page: Page, pointer: Pointer) -> None:
    """The live charts, then down to network and disk, below the fold at
    the take's zoom."""
    await pointer.click(page.locator('nav a[href="/overseer/resources"]').first)
    await page.wait_for_function(
        "() => window.Chart && Chart.getChart(document.querySelector('canvas[data-chart]'))"
    )
    await page.wait_for_timeout(HOLD)
    await center(page, "#chart-resources-network")
    await page.wait_for_timeout(HOLD)


async def scheduler(page: Page, pointer: Pointer) -> None:
    """Its jobs and when each runs next."""
    nav = page.locator('nav a[href="/overseer/components/scheduler"]').first
    await visit(page, pointer, nav)
    await center(page, "#scheduler-clock")
    await page.wait_for_timeout(HOLD)


async def database(page: Page, pointer: Pointer) -> None:
    """Its overview, then its tables."""
    await visit(
        page, pointer, page.locator('nav a[href="/overseer/components/database"]').first
    )
    tables = page.locator(
        '#app-content a[href="/overseer/components/database/tables"]'
    ).first
    await visit(page, pointer, tables)
    await page.wait_for_timeout(HOLD)


async def ask(page: Page, pointer: Pointer) -> None:
    """Typed, since the take is silent; held until her answer settles,
    then its wiring opened larger."""
    await pointer.click(page.locator("#chat-fab"))
    box = page.locator('textarea[name="message"]')
    await box.wait_for()
    await pointer.click(box, seconds=0.5)
    await box.press_sequentially(QUESTION, delay=55)
    await page.wait_for_timeout(400)
    await box.press("Enter")
    streaming = page.locator("#chat-thread [data-stream]")
    await streaming.wait_for()
    await streaming.wait_for(state="detached", timeout=180_000)
    await page.wait_for_timeout(HOLD)
    await pointer.click(page.locator('#chat-thread [data-card="path"]').last)
    await page.locator('#dialog[open] [data-card="path"]').wait_for()
    await page.wait_for_timeout(HOLD * 3)


async def main(url: str, out: Path) -> None:
    frames = out / "frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True)
    async with async_playwright() as p:
        # The scale forced at launch, not emulated: the screencast sends
        # frames at the window's CSS size under emulation, its device
        # pixels only when Chrome itself renders at the scale.
        browser = await p.chromium.launch(
            args=[
                f"--force-device-scale-factor={SCALE:.7f}",
                f"--window-size={VIEWPORT['width']},{VIEWPORT['height']}",
            ]
        )
        context = await browser.new_context(no_viewport=True, color_scheme="dark")
        await context.add_init_script(CURSOR)
        page = await context.new_page()
        cast = Screencast(await context.new_cdp_session(page), frames)
        pointer = Pointer(page)
        await overview(page, url)
        await cast.start()
        marks = []
        for shot, step in (
            ("overview", lambda: page.wait_for_timeout(HOLD)),
            ("resources", lambda: resources(page, pointer)),
            ("scheduler", lambda: scheduler(page, pointer)),
            ("database", lambda: database(page, pointer)),
            ("ask", lambda: ask(page, pointer)),
        ):
            marks.append(f"{shot} {cast.since_start():.2f}")
            await step()
        marks.append(f"end {cast.since_start():.2f}")
        await cast.stop()
        await browser.close()
    cast.encode(out / "overseer.mp4")
    (out / "marks.txt").write_text("\n".join(marks) + "\n")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1].rstrip("/"), Path(sys.argv[2])))
