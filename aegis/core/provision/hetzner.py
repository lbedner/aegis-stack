"""Hetzner Cloud: price lookup, SSH key, server create/get/delete."""

import base64
import hashlib
from typing import Any

from .http import ProvisionError, Requester

API_URL = "https://api.hetzner.cloud/v1"
IMAGE = "ubuntu-24.04"


def ssh_fingerprint(public_key: str) -> str:
    """MD5 fingerprint in Hetzner's colon form, used to find an uploaded key."""
    blob = base64.b64decode(public_key.split()[1])
    digest = hashlib.md5(blob, usedforsecurity=False).hexdigest()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def cloud_init_user_data(setup_script: str) -> str:
    """The project's ``scripts/server-setup.sh`` as first-boot user-data.

    cloud-init runs a ``#!`` user-data as root on first boot, so the box
    arrives in the state ``aegis deploy-setup`` would leave it in. HOME is
    set first: cloud-init does not export it and the script runs ``set -u``.
    """
    return f"#!/bin/bash\nexport HOME=/root\n{setup_script}"


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
        suffix = ssh_fingerprint(public_key).replace(":", "")[:8]
        created = self._request(
            "POST",
            "/ssh_keys",
            {"name": f"aegis-{name}-{suffix}", "public_key": public_key},
        )
        return created["ssh_key"]["id"], True

    def create_server(
        self, name: str, size: str, region: str, ssh_key_id: int, user_data: str
    ) -> tuple[int, str]:
        """Create the server; return ``(server_id, ipv4)``."""
        body: dict[str, Any] = {
            "name": name,
            "server_type": size,
            "location": region,
            "image": IMAGE,
            "ssh_keys": [ssh_key_id],
            "user_data": user_data,
            "labels": {"managed-by": "aegis", "aegis-project": name},
        }
        server = self._request("POST", "/servers", body)["server"]
        return server["id"], server["public_net"]["ipv4"]["ip"]

    def server_status(self, server_id: int) -> str:
        return self._request("GET", f"/servers/{server_id}")["server"]["status"]

    def delete_server(self, server_id: int) -> None:
        self._delete(f"/servers/{server_id}")

    def delete_ssh_key(self, key_id: int) -> None:
        self._delete(f"/ssh_keys/{key_id}")

    def _delete(self, path: str) -> None:
        """Delete, treating "already gone" as done so cleanup can be re-run."""
        try:
            self._request("DELETE", path)
        except ProvisionError as exc:
            if exc.status != 404:
                raise
