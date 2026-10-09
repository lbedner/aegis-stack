"""Grouping by application paths/functions, excluding line numbers.

Only paths rooted at app/ are deployment-normalized. External-only traces keep
file/function identity as a conservative fallback. Message-only errors retain
meaningful numbers/text; only UUIDs and explicitly named request IDs normalize.
Changing these rules bumps ``VERSION``, which every digest includes.
"""

import hashlib
import json
import re

VERSION = 1
# One frame of a Python traceback: its file, line and function.
FRAME = re.compile(
    r'File "(?P<path>[^"\n]+)", line (?P<line>\d+), in (?P<function>[^\n]+)'
)
UUID = re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b")
REQUEST = re.compile(r"\b(request[_ -]?id[=: ]+)\S+", re.IGNORECASE)


def digest(parts: list[object]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def app_path(path: str) -> str | None:
    """A frame's file as the app's own (``app/...``), wherever it was
    deployed; None for a library's or anything else outside ``app/``."""
    path = path.replace("\\", "/")
    if "/app/" in path:
        return "app/" + path.split("/app/", 1)[1]
    return path if path.startswith("app/") else None


def fingerprint(
    service: str,
    page: str,
    exception: str | None,
    trace: str | None,
    logger: str | None,
    message: str,
    app_service: str | None = None,
) -> str:
    frames = [
        (frame["path"].replace("\\", "/"), frame["function"].strip())
        for frame in FRAME.finditer(trace or "")
    ]
    application = [
        (own, function) for path, function in frames if (own := app_path(path))
    ]
    cause: object = (
        application
        or frames
        or REQUEST.sub(
            r"\1<id>", UUID.sub("<uuid>", message + ("\n" + trace if trace else ""))
        )
    )
    return digest(
        [
            VERSION,
            app_service,
            service,
            page,
            exception,
            cause,
            logger if not frames else None,
        ]
    )
