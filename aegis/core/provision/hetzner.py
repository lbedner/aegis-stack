"""Hetzner Cloud: price lookup, SSH key, server create/get/delete."""

from typing import Any

from .http import ProvisionError, Requester, delete
from .provider import ssh_fingerprint, ssh_key_name

API_URL = "https://api.hetzner.cloud/v1"
IMAGE = "ubuntu-24.04"


class HetznerClient:
    def __init__(self, request: Requester) -> None:
        self._request = request

    def monthly_price(self, size: str, region: str) -> str:
        """Gross monthly price of ``size`` in ``region``, e.g. ``"4.15"``."""
        types = self._request("GET", f"/server_types?name={size}")["server_types"]
        if not types:
            raise ProvisionError(f"Unknown Hetzner server type: {size}")
        prices = types[0]["prices"]
        for price in prices:
            if price["location"] == region:
                return f"{float(price['price_monthly']['gross']):.2f}"
        available = ", ".join(p["location"] for p in prices)
        raise ProvisionError(
            f"{size} is not offered in {region}; available: {available}"
        )

    def ensure_ssh_key(self, name: str, public_key: str) -> tuple[int, bool]:
        """Return ``(key_id, created)``, uploading the key only if it is new."""
        found = self._request(
            "GET", f"/ssh_keys?fingerprint={ssh_fingerprint(public_key)}"
        )["ssh_keys"]
        if found:
            return found[0]["id"], False
        created = self._request(
            "POST",
            "/ssh_keys",
            {"name": ssh_key_name(name, public_key), "public_key": public_key},
        )
        return created["ssh_key"]["id"], True

    def create_server(
        self, name: str, size: str, region: str, ssh_key_id: int, user_data: str
    ) -> int:
        body: dict[str, Any] = {
            "name": name,
            "server_type": size,
            "location": region,
            "image": IMAGE,
            "ssh_keys": [ssh_key_id],
            "user_data": user_data,
            "labels": {"managed-by": "aegis", "aegis-project": name},
        }
        return self._request("POST", "/servers", body)["server"]["id"]

    def running_ipv4(self, server_id: int) -> str | None:
        server = self._request("GET", f"/servers/{server_id}")["server"]
        if server["status"] != "running":
            return None
        return server["public_net"]["ipv4"]["ip"]

    def create_firewall(self, name: str, server_id: int) -> str | None:
        # ponytail: no cloud firewall on Hetzner yet, so Docker-published ports
        # skip ufw there; add one as DigitalOcean does when that matters.
        return None

    def delete_server(self, server_id: int) -> None:
        delete(self._request, f"/servers/{server_id}")

    def delete_ssh_key(self, key_id: int) -> None:
        delete(self._request, f"/ssh_keys/{key_id}")

    def delete_firewall(self, firewall_id: str) -> None:
        delete(self._request, f"/firewalls/{firewall_id}")
