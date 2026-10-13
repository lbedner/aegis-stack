"""DigitalOcean: price lookup, SSH key, droplet create/get/delete, cloud firewall."""

from typing import Any

from .http import ProvisionError, Requester, delete
from .provider import amount, ssh_fingerprint, ssh_key_name

API_URL = "https://api.digitalocean.com/v2"
IMAGE = "ubuntu-24-04-x64"
# Docker publishes ports around ufw, so the firewall outside the droplet is
# the one that holds: SSH, HTTP and HTTPS in, everything out.
OPEN_PORTS = ("22", "80", "443")
_ANYWHERE = {"addresses": ["0.0.0.0/0", "::/0"]}
MANAGED_TAG = "managed-by-aegis"
PROJECT_TAG = "aegis-project:"


class DigitalOceanClient:
    def __init__(self, request: Requester) -> None:
        self._request = request

    def account(self) -> dict[str, Any]:
        """Droplets (``droplet:read``) and this month's spend
        (``billing:read``, said missing when the token lacks it)."""
        try:
            droplets = self._request("GET", "/droplets?per_page=200")["droplets"]
        except ProvisionError as exc:
            if exc.status == 403:
                raise ProvisionError(
                    "The token cannot list droplets: give it droplet:read.", 403
                ) from None
            raise
        servers = [
            {
                "name": d["name"],
                "size": d["size_slug"],
                "region": d["region"]["slug"],
                "price": amount(d["size"]["price_monthly"]),
                "created": d["created_at"],
                "project": next(
                    (
                        t.removeprefix(PROJECT_TAG)
                        for t in d.get("tags") or ()
                        if t.startswith(PROJECT_TAG)
                    ),
                    None,
                ),
            }
            for d in droplets
        ]
        try:
            spent = self._request("GET", "/customers/my/balance")["month_to_date_usage"]
        except ProvisionError as exc:
            if exc.status != 403:
                raise
            return {
                "servers": servers,
                "month_to_date": None,
                "missing": ["billing:read"],
            }
        return {
            "servers": servers,
            "month_to_date": amount(spent),
            "missing": [],
        }

    def catalog(self) -> dict[str, Any]:
        """Sizes on sale, priced (one price everywhere) in each region open
        to new droplets that offers them."""
        regions = [
            r
            for r in self._request("GET", "/regions?per_page=200")["regions"]
            if r.get("available")
        ]
        open_now = {r["slug"] for r in regions}
        sizes = []
        for size in self._request("GET", "/sizes?per_page=200")["sizes"]:
            price = amount(size["price_monthly"])
            prices = {r: price for r in size["regions"] if r in open_now}
            if size.get("available") and prices:
                sizes.append(
                    {
                        "slug": size["slug"],
                        "group": size.get("description") or "Other",
                        "memory_mb": size["memory"],
                        "vcpus": size["vcpus"],
                        "disk_gb": size["disk"],
                        "prices": prices,
                    }
                )
        names = [{"slug": r["slug"], "name": r["name"]} for r in regions]
        return {"sizes": sizes, "regions": names}

    def ensure_ssh_key(self, name: str, public_key: str) -> tuple[int, bool]:
        """Return ``(key_id, created)``, uploading the key only if it is new."""
        try:
            path = f"/account/keys/{ssh_fingerprint(public_key)}"
            return self._request("GET", path)["ssh_key"]["id"], False
        except ProvisionError as exc:
            if exc.status != 404:
                raise
        created = self._request(
            "POST",
            "/account/keys",
            {"name": ssh_key_name(name, public_key), "public_key": public_key},
        )
        return created["ssh_key"]["id"], True

    def create_server(
        self, name: str, size: str, region: str, ssh_key_id: int, user_data: str
    ) -> int:
        body: dict[str, Any] = {
            "name": name,
            "region": region,
            "size": size,
            "image": IMAGE,
            "ssh_keys": [ssh_key_id],
            "user_data": user_data,
            "tags": [MANAGED_TAG, f"{PROJECT_TAG}{name}"],
        }
        return self._request("POST", "/droplets", body)["droplet"]["id"]

    def running_ipv4(self, server_id: int) -> str | None:
        """The public IPv4 once active; a new droplet has no address yet."""
        droplet = self._request("GET", f"/droplets/{server_id}")["droplet"]
        if droplet["status"] != "active":
            return None
        public = [n for n in droplet["networks"]["v4"] if n["type"] == "public"]
        return public[0]["ip_address"] if public else None

    def create_firewall(self, name: str, server_id: int) -> str | None:
        body = {
            "name": f"aegis-{name}",
            "inbound_rules": [
                {"protocol": "tcp", "ports": port, "sources": _ANYWHERE}
                for port in OPEN_PORTS
            ],
            "outbound_rules": [
                {"protocol": "tcp", "ports": "0", "destinations": _ANYWHERE},
                {"protocol": "udp", "ports": "0", "destinations": _ANYWHERE},
                {"protocol": "icmp", "destinations": _ANYWHERE},
            ],
            "droplet_ids": [server_id],
        }
        return self._request("POST", "/firewalls", body)["firewall"]["id"]

    def delete_server(self, server_id: int) -> None:
        delete(self._request, f"/droplets/{server_id}")

    def delete_ssh_key(self, key_id: int) -> None:
        delete(self._request, f"/account/keys/{key_id}")

    def delete_firewall(self, firewall_id: str) -> None:
        delete(self._request, f"/firewalls/{firewall_id}")
