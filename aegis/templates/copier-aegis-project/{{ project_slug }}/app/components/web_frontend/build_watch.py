"""Re-run ``build_assets`` whenever a watched static source changes.

Plugs the gap between Tailwind (which only writes raw
``static/dist/app.css``) and ``build.py`` (which fingerprints it and emits
``manifest.json``). Without this the manifest goes stale the moment
Tailwind rebuilds: the browser keeps loading the previous fingerprinted
filename until somebody runs ``make build-static``.

Watches the same sources ``build.py`` fingerprints, debounces flurries of
writes (Tailwind emits several events per save), and runs
``build_assets()`` once per quiet period. Fail-soft: a watchdog blip logs
and keeps watching, because a CSS edit should never take down the dev
stack.

Run as ``python -m app.components.web_frontend.build_watch``.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from app.components.web_frontend.build import (
    SOURCE_TREES,
    STATIC_DIR,
    TAILWIND_OUTPUT,
    build_assets,
)
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

logger = logging.getLogger("build_watch")

# Poll rather than wait on filesystem events: on a Docker Desktop bind
# mount, edits made on the host do not reliably raise inotify events in the
# container, and an event-driven watcher then serves stale JS without a
# word. A handful of small source trees costs nothing to stat each second.
OBSERVER = PollingObserver
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [build-watch] %(message)s",
    datefmt="%H:%M:%S",
)

# Debounce window. Tailwind writes its output in a few quick events (open /
# write / close); without this each one would spawn a separate fingerprint
# pass. 250ms is short enough that the manifest is current by the time the
# human flips back to the browser.
DEBOUNCE_SECONDS = 0.25


def _is_source(raw_path: str) -> bool:
    """True when ``raw_path`` is an input to fingerprinting.

    Everything under ``dist/`` except the Tailwind output is this script's
    own output. Reacting to it would make each rebuild trigger the next one
    and the watcher would spin forever.
    """
    try:
        rel = Path(raw_path).resolve().relative_to(STATIC_DIR.resolve())
    except (ValueError, OSError):
        return False
    if rel.as_posix() == TAILWIND_OUTPUT:
        return True
    if not rel.parts or rel.parts[0] == "dist":
        return False
    return any(
        rel.parts[0] == subdir and rel.suffix == suffix
        for subdir, suffix in SOURCE_TREES
    )


def _watched_dirs() -> list[tuple[Path, bool]]:
    """``(directory, recursive)`` pairs for the observer.

    The source trees are watched recursively so a newly added file is
    picked up without restarting. ``dist/`` is watched shallowly and only
    for the Tailwind output; its subdirectories hold generated copies.
    """
    dirs: list[tuple[Path, bool]] = []
    for subdir, _ in SOURCE_TREES:
        path = STATIC_DIR / subdir
        if path.is_dir():
            dirs.append((path, True))
    dist = STATIC_DIR / (Path(TAILWIND_OUTPUT).parent)
    if dist.is_dir():
        dirs.append((dist, False))
    return dirs


class _DebouncedRebuild(FileSystemEventHandler):
    """Marks the tree dirty on each relevant event; ``maybe_run`` drains at
    most once per ``DEBOUNCE_SECONDS``, so a burst of writes to
    ``dist/app.css`` produces a single fingerprint pass."""

    def __init__(self) -> None:
        self._dirty_at: float | None = None

    def on_any_event(self, event: FileSystemEvent) -> None:
        # ``build_assets()`` reads every source via ``read_bytes()``, which
        # fires open/close events on those same files. Reacting to them
        # would loop the watcher, so only real edits (modified / created /
        # moved) count.
        if event.event_type in ("opened", "closed", "closed_no_write"):
            return
        if not _is_source(str(event.src_path)):
            return
        self._dirty_at = time.monotonic()

    def maybe_run(self) -> None:
        if self._dirty_at is None:
            return
        if time.monotonic() - self._dirty_at < DEBOUNCE_SECONDS:
            return
        self._dirty_at = None
        try:
            built = build_assets()
            logger.info("rebuilt manifest (%d assets)", len(built))
        except Exception as exc:
            # Soft-fail: a partial write or transient FS hiccup shouldn't
            # take the watcher down. The next event re-arms it.
            logger.warning("rebuild failed: %s", exc)


def main() -> int:
    # Bootstrap first: it makes the manifest current before the first event
    # lands (removing a "stale on first load" race when the watcher starts
    # after Tailwind has already written), and it creates dist/ so the
    # observer below has a directory to watch.
    try:
        build_assets()
        logger.info("initial fingerprint pass complete")
    except Exception as exc:
        logger.warning("initial pass failed: %s", exc)

    handler = _DebouncedRebuild()
    observer = OBSERVER(timeout=1)
    for directory, recursive in _watched_dirs():
        observer.schedule(handler, str(directory), recursive=recursive)
    observer.start()

    try:
        while True:
            handler.maybe_run()
            time.sleep(0.1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
