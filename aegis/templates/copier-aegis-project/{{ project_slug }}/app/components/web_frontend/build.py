"""Asset fingerprinting for the web frontend.

Hashes every CSS/JS asset under ``static/`` and emits a content-addressed
copy under ``static/dist/`` along with a ``manifest.json`` mapping logical
paths to built paths. The ``static()`` Jinja global reads that manifest, so
templates emit hashed URLs that ``CachedStaticFiles`` can serve as
immutable for a year.

Runs in two places:

- Docker build (prod): invoked in the runtime stage after the Tailwind
  output lands, so the image ships with a manifest.
- Dev (optional): run ``make build-static`` to preview the fingerprinted
  behaviour. When the manifest is absent — the common dev case — the
  ``static()`` helper degrades to unhashed paths, pages still render, and
  a one-hour Cache-Control plus ETag keeps the traffic cheap.

Pure stdlib on purpose: this runs before ``uv sync`` has finished in the
Docker build stage.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"
DIST_DIR = STATIC_DIR / "dist"
MANIFEST_PATH = DIST_DIR / "manifest.json"

# Tailwind's compiled output. It already lives in dist/, so its
# fingerprinted copy sits next to the original rather than nesting.
TAILWIND_OUTPUT = "dist/app.css"

# Directories scanned for hand-authored assets, and the extension each
# holds. Add a file to either and it is fingerprinted automatically; no
# list to keep in sync.
SOURCE_TREES: tuple[tuple[str, str], ...] = (
    ("css", ".css"),
    ("js", ".js"),
    ("vendor", ".js"),
)


def iter_sources() -> list[tuple[str, str]]:
    """Return ``(source_rel, output_template)`` pairs to fingerprint.

    ``output_template`` carries a ``{hash}`` placeholder filled with the
    first 8 hex chars of the content sha256. Everything already under
    ``dist/`` is skipped apart from the Tailwind output itself: the rest of
    that directory is this script's own output, and fingerprinting it would
    compound on every run.
    """
    sources: list[tuple[str, str]] = []

    if (STATIC_DIR / TAILWIND_OUTPUT).is_file():
        sources.append((TAILWIND_OUTPUT, "dist/app-{hash}.css"))

    for subdir, suffix in SOURCE_TREES:
        root = STATIC_DIR / subdir
        if not root.is_dir():
            continue
        for path in sorted(root.rglob(f"*{suffix}")):
            rel = path.relative_to(STATIC_DIR).as_posix()
            stem = rel[: -len(suffix)]
            sources.append((rel, f"dist/{stem}-{{hash}}{suffix}"))

    return sources


def _short_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]


def build_assets() -> dict[str, str]:
    """Hash each source, copy it to its fingerprinted name, return the manifest.

    Idempotent: unchanged sources produce the same hashes, the same
    filenames and the same manifest, so this is safe to run on every build.
    """
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    for source_rel, output_template in iter_sources():
        src = STATIC_DIR / source_rel
        if not src.is_file():
            # Raced with a rebuild between glob and read; the next pass
            # picks it up.
            continue
        data = src.read_bytes()
        output_rel = output_template.format(hash=_short_hash(data))
        dest = STATIC_DIR / output_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        manifest[source_rel] = output_rel
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


if __name__ == "__main__":
    built = build_assets()
    print(f"built {len(built)} asset(s) -> {MANIFEST_PATH}", file=sys.stderr)
