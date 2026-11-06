"""What a DNS change decides, for the ``dns`` CLI and Overseer >
Deployments > DNS alike: the domain (``BASE_DOMAIN``), the registrar,
and a record from what was typed, an A record pointing at the server
this project deploys to unless told otherwise."""

from app.core.config import settings
from app.services.ops.adapters.porkbun import PorkbunAdapter
from app.services.ops.adapters.porkbun_records import (
    PORKBUN_PRIORITIZED,
    PORKBUN_TTL_FLOOR,
)
from app.services.ops.types import DnsRecord, RetrievedRecord
from app.services.system import hosting

# The registrar, as the provider table has it (its name, logo and keys);
# its TTL floor, and the types it keeps a priority for.
PROVIDER = hosting.BY_KEY[PorkbunAdapter.name]
TTL = PORKBUN_TTL_FLOOR
PRIORITIZED = PORKBUN_PRIORITIZED


def domain() -> str:
    """The domain whose records these are; empty where none is set."""
    return (settings.BASE_DOMAIN or "").strip().lower()


def registrar() -> PorkbunAdapter:
    """The registrar adapter. One concrete class today; this is the seam
    where a future provider switch would live."""
    return PorkbunAdapter()


def server_ip() -> str | None:
    """The server this project deploys to (``.aegis/deploy.yml``), if any."""
    return (hosting.deploy_config().get("server") or {}).get("host")


def host(name: str) -> str:
    """The relative host ``name`` (``@`` for the apex) is, as the
    registrar keeps it: ``""`` for the apex."""
    found = name.strip().lower()
    return "" if found == "@" else found


def fields(record: RetrievedRecord) -> dict[str, str]:
    """``record`` as one reads it, and as its form holds it: ``@`` for the
    apex, no priority where it has none."""
    return {
        "host": record.host or "@",
        "type": record.type,
        "value": record.value,
        "ttl": str(record.ttl),
        "priority": "" if record.priority is None else str(record.priority),
    }


def label(host: str, apex: str) -> str:
    """``host`` on ``apex`` as one reads it: ``www.example.com``."""
    return f"{host}.{apex}" if host else apex


def record(
    name: str,
    type_: str = "A",
    value: str | None = None,
    ttl: int = TTL,
    priority: int | None = None,
) -> DnsRecord:
    """The record ``name`` (``@`` for the apex) is to have; an A record's
    ``value`` is the server's unless given. ValueError says what is
    missing."""
    kind = type_.strip().upper()
    found = (value or "").strip() or (server_ip() if kind == "A" else None)
    if not found:
        if kind == "A":
            raise ValueError(
                "An A record needs its IP: no server in .aegis/deploy.yml."
            )
        raise ValueError(f"A {kind} record needs its value.")
    return DnsRecord(
        host=host(name),
        type=kind,
        value=found,
        ttl=ttl,
        priority=priority,
    )
