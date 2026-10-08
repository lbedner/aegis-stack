"""What a part of the app keeps in Redis, declared beside the code that
writes it (``REDIS_KEYS = (KeyFamily(...), ...)``).

Here, in core, so declaring keys imports nothing else: a worker module
declaring its keys must not load the system service (its health checks
and alerts) to do it. The keyspace map that reads them is
``app.services.system.redis_keys``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class KeyFamily:
    """Keys one part of the app owns, in its own words.

    ``db`` names the settings field holding the logical database;
    ``columns`` label a peek at the newest key (a sorted set's member and
    score, a hash's field and value).
    """

    pattern: str
    kind: str
    name: str
    purpose: str
    owner: str
    db: str = "REDIS_DB"
    columns: tuple[str, str] = ("Member", "Value")
