"""Porkbun DNS: one A record for the provisioned server. Its keys travel in
each request's body (``json_requester(body=...)``), never a header."""

from .http import ProvisionError, Requester

API_URL = "https://api.porkbun.com/api/json/v3"
TTL = "600"  # the least Porkbun takes
# What Porkbun answers for a domain it will not touch: not in the account,
# or its API ACCESS off.
_NOT_THERE = (400, 403, 404)


class PorkbunDNS:
    def __init__(self, request: Requester) -> None:
        self._request = request

    def _domain(self, hostname: str) -> str:
        """The account's domain that ``hostname`` is in: the longest suffix
        Porkbun answers for."""
        labels = hostname.split(".")
        for i in range(len(labels) - 1):
            domain = ".".join(labels[i:])
            try:
                self._request("POST", f"/dns/retrieve/{domain}")
            except ProvisionError as exc:
                if exc.status not in _NOT_THERE:
                    raise
                continue
            return domain
        raise ProvisionError(
            f"No Porkbun domain found for {hostname}: is it in this account, "
            "with API ACCESS on (the domain's details on porkbun.com)?"
        )

    def create_a_record(self, hostname: str, ip: str) -> tuple[str, str]:
        """Point ``hostname`` at ``ip``; return ``(domain, record_id)``."""
        domain = self._domain(hostname)
        name = hostname.removesuffix(domain).rstrip(".")
        created = self._request(
            "POST",
            f"/dns/create/{domain}",
            {"name": name, "type": "A", "content": ip, "ttl": TTL},
        )
        return domain, str(created["id"])

    def delete_record(self, zone_id: str, record_id: str) -> None:
        """Delete it from its domain (``zone_id``: Porkbun's zone is one)."""
        self._request("POST", f"/dns/delete/{zone_id}/{record_id}")
