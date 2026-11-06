"""The Porkbun adapter's DNS edit: the record keeps its id, its fields
replaced, as Porkbun's ``/dns/edit/<domain>/<id>`` takes them."""

from typing import Any

import pytest

from app.services.ops.adapters.porkbun import PorkbunAdapter
from app.services.ops.types import DnsRecord


def _posting(
    monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []

    async def post(self: PorkbunAdapter, path: str, payload: dict[str, Any]) -> Any:
        sent.append((path, payload))
        return answer

    monkeypatch.setattr(PorkbunAdapter, "_post", post)
    return sent


async def test_an_edit_replaces_the_records_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _posting(monkeypatch, {"status": "SUCCESS"})
    record = DnsRecord(host="www", type="A", value="198.51.100.9", ttl=300)
    await PorkbunAdapter().edit_dns_record("example.com", "42", record)
    assert sent == [
        (
            "/dns/edit/example.com/42",
            {"name": "www", "type": "A", "content": "198.51.100.9", "ttl": "600"},
        )
    ]


async def test_a_refused_edit_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    _posting(monkeypatch, {"status": "ERROR", "message": "Invalid record id."})
    record = DnsRecord(host="", type="A", value="198.51.100.9")
    with pytest.raises(RuntimeError, match="Invalid record id."):
        await PorkbunAdapter().edit_dns_record("example.com", "42", record)


async def test_a_listed_priority_is_only_where_its_type_has_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Porkbun answers a priority of 0 for every type; only MX and SRV use
    one, so the CLI's list and Overseer's both show none for the rest."""

    async def retrieve(self: PorkbunAdapter, domain: str) -> list[dict[str, Any]]:
        row = {"id": "1", "name": "example.com", "content": "x", "ttl": "600"}
        return [row | {"type": "A", "prio": "0"}, row | {"type": "MX", "prio": "10"}]

    monkeypatch.setattr(PorkbunAdapter, "_retrieve_raw", retrieve)
    found = await PorkbunAdapter().list_dns_records("example.com")
    assert [(r.type, r.priority) for r in found] == [("A", None), ("MX", 10)]
