"""Context for the Overseer Storage page's sections.

Overview: the app's bucket (how much it holds and at what sizes) and the
Flet storage modal's connection details. Browse: any bucket, folder by
folder. The listing is capped
(``LIMIT``) the same way the Redis keyspace is; past it the numbers are a
floor and say so.
"""

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from app.core.formatting import format_bytes, format_relative_time
from app.core.log import logger
from app.core.storage import get_storage
from app.services.system.models import ComponentStatus, ComponentStatusType

from .overseer_nav import SectionRequest

SECTIONS = ((None, {"overview": "Overview", "browse": "Browse"}),)

PARTIALS = "/partials/overseer/storage"

LIMIT = 10_000
# Entries shown per level when browsing a bucket.
BROWSE_LIMIT = 1000
# (upper bound in bytes, label); the last band has no upper bound.
SIZE_BANDS = (
    (1024, "Under 1 KB"),
    (1024**2, "1 KB to 1 MB"),
    (10 * 1024**2, "1 MB to 10 MB"),
    (None, "10 MB and over"),
)


async def load_objects() -> dict[str, Any]:
    """The bucket's objects, or why they could not be read."""
    lister = getattr(get_storage(), "list_objects", None)
    if lister is None:
        return {"error": "The filesystem store is not listed here.", "objects": []}
    try:
        objects, truncated = await lister(LIMIT)
    except Exception as exc:  # noqa: BLE001 - shown on the page, logged here
        logger.warning("Storage listing failed", error=str(exc))
        return {"error": str(exc), "objects": []}
    return {"error": None, "objects": objects, "truncated": truncated}


def _ago(when: Any) -> str:
    return format_relative_time(
        when.isoformat() if hasattr(when, "isoformat") else when
    )


def _band(size: int) -> str:
    return next(label for bound, label in SIZE_BANDS if bound is None or size < bound)


def summarize(listing: dict[str, Any]) -> dict[str, Any]:
    """Counts and a size histogram for the Overview."""
    objects = listing["objects"]
    floor = "+" if listing.get("truncated") else ""
    total = sum(o["size"] for o in objects)
    latest = max((o["modified"] for o in objects if o.get("modified")), default=None)
    counts = {label: [0, 0] for _, label in SIZE_BANDS}
    for o in objects:
        counts[_band(o["size"])][0] += 1
        counts[_band(o["size"])][1] += o["size"]
    most = max((n for n, _ in counts.values()), default=0)
    return {
        "error": listing["error"],
        "count": f"{len(objects):,}{floor}",
        "stored": format_bytes(total) + floor,
        "largest": format_bytes(max((o["size"] for o in objects), default=0)),
        "latest": _ago(latest) if latest else "-",
        "empty": not objects and listing["error"] is None,
        "bands": [
            {
                "label": label,
                "count": f"{n:,}",
                "value": format_bytes(size),
                "ratio": n / most if most else 0,
            }
            for label, (n, size) in counts.items()
        ],
    }


def _link(path: str, **params: str) -> str:
    query = urlencode({k: v for k, v in params.items() if v})
    return f"{path}?{query}" if query else path


def _crumbs(path: str, bucket: str, prefix: str) -> tuple[list[dict[str, str]], str]:
    """The trail back up (Buckets, the bucket, each folder) and where we are."""
    parts = [p for p in prefix.split("/") if p]
    trail = [(bucket, "")] + [
        (part, "/".join(parts[: i + 1]) + "/") for i, part in enumerate(parts)
    ]
    crumbs = [{"label": "Buckets", "url": _link(path)}] + [
        {"label": label, "url": _link(path, bucket=bucket, prefix=at)}
        for label, at in trail[:-1]
    ]
    return crumbs, trail[-1][0]


def writable(store: Any, bucket: str) -> bool:
    """Every bucket but the app's own: its keys are content hashes that
    database rows point at, so the app writes it and nothing else does."""
    return bool(bucket) and bucket != getattr(store, "bucket", None)


def _file_links(bucket: str, key: str, can_write: bool) -> dict[str, str | None]:
    target = urlencode({"bucket": bucket, "key": key})
    return {
        "download": f"{PARTIALS}/download?{target}",
        "delete": f"{PARTIALS}/confirm-delete?{target}" if can_write else None,
    }


def _level_rows(
    path: str, bucket: str, prefix: str, level: dict[str, Any], can_write: bool
) -> list[dict[str, Any]]:
    folders = [
        {
            "name": {
                "label": folder[len(prefix) :],
                "url": _link(path, bucket=bucket, prefix=folder),
                "kind": "folder",
            },
            "pick": {"key": None},
        }
        for folder in level["folders"]
    ]
    files = [
        {
            "name": {"label": f["key"][len(prefix) :], "url": None, "kind": "file"},
            "size": format_bytes(f["size"]),
            "modified": _ago(f["modified"]) if f.get("modified") else None,
        }
        | _file_links(bucket, f["key"], can_write)
        | {"pick": {"key": f["key"] if can_write else None}}
        for f in level["files"]
    ]
    return folders + files


async def browse_view(query: Mapping[str, str], path: str) -> dict[str, Any]:
    """The buckets, or one level of one bucket, as a file browser reads it."""
    store: Any = get_storage()
    bucket, prefix = query.get("bucket") or "", query.get("prefix") or ""
    view: dict[str, Any] = {
        "crumbs": [],
        "current": "Buckets",
        "rows": [],
        "truncated": False,
        "error": None,
    }
    if not hasattr(store, "browse"):
        return view | {"error": "The filesystem store is not browsed here."}
    if bucket:
        view["crumbs"], view["current"] = _crumbs(path, bucket, prefix)
    try:
        if not bucket:
            view["rows"] = [
                {
                    "name": {
                        "label": b["name"],
                        "url": _link(path, bucket=b["name"]),
                        "kind": "bucket",
                    },
                    "modified": _ago(b["created"]) if b.get("created") else None,
                }
                for b in await store.buckets()
            ]
            return view
        level = await store.browse(bucket, prefix, BROWSE_LIMIT)
    except Exception as exc:  # noqa: BLE001 - shown on the page, logged here
        logger.warning("Storage browse failed", bucket=bucket, error=str(exc))
        return view | {"error": str(exc)}
    can_write = writable(store, bucket)
    return view | {
        "rows": _level_rows(path, bucket, prefix, level, can_write),
        "truncated": level["truncated"],
        "writable": can_write,
        "bucket": bucket,
        "prefix": prefix,
        "upload_url": f"{PARTIALS}/upload",
        "bulk_delete_url": f"{PARTIALS}/confirm-delete?{urlencode({'bucket': bucket})}",
    }


def connection(storage: ComponentStatus) -> list[tuple[str, str]]:
    metadata = storage.metadata or {}
    return [
        ("Backend", str(metadata.get("backend") or "-")),
        ("Endpoint", str(metadata.get("endpoint") or "AWS S3")),
        ("Bucket", str(metadata.get("bucket") or "-")),
        ("Region", str(metadata.get("region") or "-")),
        (
            "Status",
            "Reachable"
            if storage.status == ComponentStatusType.HEALTHY
            else storage.message,
        ),
    ]


async def section_context(
    section: str, storage: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """Browse reads one level of one bucket; the Overview reads the app's
    bucket and how the app reaches it."""
    if section == "browse":
        return {"browse": await browse_view(req.query, req.path)}
    return {
        "bucket": summarize(await load_objects()),
        "connection": connection(storage),
    }
