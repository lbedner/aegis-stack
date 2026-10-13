"""Hetzner Cloud: price lookup, SSH key, server create/get/delete."""

from typing import Any

from .http import Requester, delete
from .provider import amount, ssh_fingerprint, ssh_key_name

API_URL = "https://api.hetzner.cloud/v1"
IMAGE = "ubuntu-24.04"
PROJECT_LABEL = "aegis-project"  # which project made a server


class HetznerClient:
    def __init__(self, request: Requester) -> None:
        self._request = request

    def account(self) -> dict[str, Any]:
        """Servers, each priced (gross) where it is; Hetzner has no billing
        API, so no spend."""
        servers = []
        for s in self._request("GET", "/servers?per_page=50")["servers"]:
            where = s["datacenter"]["location"]["name"]
            prices = {p["location"]: p for p in s["server_type"]["prices"]}
            price = prices.get(where, {}).get("price_monthly", {}).get("gross")
            servers.append(
                {
                    "name": s["name"],
                    "size": s["server_type"]["name"],
                    "region": where,
                    "price": amount(price) if price else None,
                    "created": s["created"],
                    "project": (s.get("labels") or {}).get(PROJECT_LABEL),
                }
            )
        return {"servers": servers, "month_to_date": None, "missing": []}

    def catalog(self) -> dict[str, Any]:
        """Server types still sold, priced (gross) per location, grouped as
        Hetzner sells them: shared or dedicated vCPUs, x86 or Arm."""
        types = self._request("GET", "/server_types?per_page=50")["server_types"]
        sizes = [
            {
                "slug": t["name"],
                "group": f"{t['cpu_type'].title()} vCPU"
                + (", Arm" if t.get("architecture") == "arm" else ""),
                "memory_mb": round(t["memory"] * 1024),
                "vcpus": t["cores"],
                "disk_gb": t["disk"],
                "prices": {
                    p["location"]: amount(p["price_monthly"]["gross"])
                    for p in t["prices"]
                },
            }
            for t in types
            if not t.get("deprecation") and t["prices"]
        ]
        locations = self._request("GET", "/locations?per_page=50")["locations"]
        regions = [
            {"slug": loc["name"], "name": f"{loc['city']}, {loc['country']}"}
            for loc in locations
        ]
        return {"sizes": sizes, "regions": regions}

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
            "labels": {"managed-by": "aegis", PROJECT_LABEL: name},
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
