"""How a Porkbun DNS record is written and compared: the payload
``/dns/create`` and ``/dns/edit`` take, a host relative to its domain, and
the key two records match on. Beside ``porkbun.py`` rather than in it, so
the adapter keeps to its calls.
"""

from typing import Any

from app.services.ops.types import DnsRecord

# Porkbun's floor: a shorter TTL is clamped to it.
PORKBUN_TTL_FLOOR = 600
# The types a priority means anything for; Porkbun answers 0 for the rest.
PORKBUN_PRIORITIZED = frozenset({"MX", "SRV"})


def payload(record: DnsRecord, domain: str) -> dict[str, Any]:
    """``record`` as ``/dns/create`` and ``/dns/edit`` take it: its host
    relative to ``domain``, its TTL no lower than Porkbun's floor."""
    found: dict[str, Any] = {
        "name": relative_host(record.host, domain),
        "type": record.type.upper(),
        "content": record.value,
        "ttl": str(max(record.ttl, PORKBUN_TTL_FLOOR)),
    }
    if record.priority is not None:
        found["prio"] = str(record.priority)
    return found


def relative_host(host: str, registered_domain: str) -> str:
    """Return the **relative** host Porkbun expects in a `name` field.

    Examples (registered_domain = ``example.com``):

    - ``"send"``                       → ``"send"``        (already relative)
    - ``"send.app"``                   → ``"send.app"``    (already relative)
    - ``"send.app.example.com"``       → ``"send.app"``    (trim parent)
    - ``"example.com"``                → ``""``            (apex)
    - ``""`` / ``"@"``                 → ``""``            (apex shorthand)
    """
    h = (host or "").strip()
    if not h or h == "@":
        return ""
    if h.lower() == registered_domain.lower():
        return ""
    suffix = "." + registered_domain.lower()
    if h.lower().endswith(suffix):
        return h[: -len(suffix)]
    return h


def match_key(record: dict[str, Any], domain: str) -> tuple[str, str, str]:
    """Stable key for idempotency comparison against Porkbun records.

    Match on ``(type, relative-name, value)`` so a record with the same
    effective spec is treated as the same: Porkbun lists names fully
    qualified, a payload carries them relative. Lowercase normalisation on
    type and name keeps the comparison case-insensitive.
    """
    rtype = str(record.get("type") or "").upper()
    name = relative_host(str(record.get("name") or ""), domain).lower()
    value = str(record.get("content") or "")
    return (rtype, name, value)
