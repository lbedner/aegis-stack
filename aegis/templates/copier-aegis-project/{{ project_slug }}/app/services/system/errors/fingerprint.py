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
FRAME = re.compile(r'File "([^"\n]+)", line \d+, in ([^\n]+)')
UUID = re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b")
REQUEST = re.compile(r"\b(request[_ -]?id[=: ]+)\S+", re.IGNORECASE)


def digest(parts: list[object]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


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
        (path.replace("\\", "/"), function.strip())
        for path, function in FRAME.findall(trace or "")
    ]
    application = [
        ("app/" + path.split("/app/", 1)[1] if "/app/" in path else path, function)
        for path, function in frames
        if "/app/" in path or path.startswith("app/")
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
