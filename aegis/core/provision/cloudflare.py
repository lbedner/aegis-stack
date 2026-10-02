"""Cloudflare DNS: one A record for the provisioned server."""

from .http import ProvisionError, Requester

API_URL = "https://api.cloudflare.com/client/v4"


class CloudflareDNS:
    def __init__(self, request: Requester) -> None:
        self._request = request

    def _zone_id(self, hostname: str) -> str:
        """The zone that owns ``hostname``: the longest suffix Cloudflare knows."""
        labels = hostname.split(".")
        for i in range(len(labels) - 1):
            zone = ".".join(labels[i:])
            result = self._request("GET", f"/zones?name={zone}")["result"]
            if result:
                return result[0]["id"]
        raise ProvisionError(f"No Cloudflare zone found for {hostname}")

    def create_a_record(self, hostname: str, ip: str) -> tuple[str, str]:
        """Point ``hostname`` at ``ip``; return ``(zone_id, record_id)``.

        Unproxied, so Let's Encrypt and SSH reach the server itself.
        """
        zone_id = self._zone_id(hostname)
        record = self._request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            {"type": "A", "name": hostname, "content": ip, "ttl": 60, "proxied": False},
        )["result"]
        return zone_id, record["id"]

    def delete_record(self, zone_id: str, record_id: str) -> None:
        try:
            self._request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")
        except ProvisionError as exc:
            if exc.status != 404:
                raise
