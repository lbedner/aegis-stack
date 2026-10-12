"""The provider seam: what ``aegis deploy-provision`` needs from a cloud.

Each cloud's client implements ``ProviderClient``; ``registry.PROVIDERS`` says
which clients exist. The helpers below are shared by every client.
"""

import base64
import hashlib
from typing import Protocol


class ProviderClient(Protocol):
    def monthly_price(self, size: str, region: str) -> str:
        """Monthly price of ``size`` in ``region``, e.g. ``"4.15"``."""
        ...

    def ensure_ssh_key(self, name: str, public_key: str) -> tuple[int, bool]:
        """``(key_id, created)``, uploading the key only if it is new."""
        ...

    def create_server(
        self, name: str, size: str, region: str, ssh_key_id: int, user_data: str
    ) -> int:
        """Create the server; return its id."""
        ...

    def running_ipv4(self, server_id: int) -> str | None:
        """The public IPv4 once the server is running, else None."""
        ...

    def create_firewall(self, name: str, server_id: int) -> str | None:
        """Attach a cloud firewall (22/80/443 in); its id, or None if none is made."""
        ...

    def delete_server(self, server_id: int) -> None: ...

    def delete_ssh_key(self, key_id: int) -> None: ...

    def delete_firewall(self, firewall_id: str) -> None: ...


def ssh_fingerprint(public_key: str) -> str:
    """MD5 fingerprint in colon form, how clouds find an uploaded key."""
    blob = base64.b64decode(public_key.split()[1])
    digest = hashlib.md5(blob, usedforsecurity=False).hexdigest()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def ssh_key_name(name: str, public_key: str) -> str:
    """The name a key is uploaded under: the project plus its fingerprint."""
    return f"aegis-{name}-{ssh_fingerprint(public_key).replace(':', '')[:8]}"


def cloud_init_user_data(setup_script: str) -> str:
    """The project's ``scripts/server-setup.sh`` as first-boot user-data.

    cloud-init runs a ``#!`` user-data as root on first boot, so the box
    arrives in the state ``aegis deploy-setup`` would leave it in. HOME is
    set first: cloud-init does not export it and the script runs ``set -u``.
    """
    return f"#!/bin/bash\nexport HOME=/root\n{setup_script}"
