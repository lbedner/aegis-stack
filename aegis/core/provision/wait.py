"""Polling for a new server: host key up, name resolving."""

import socket
import subprocess
import time
from collections.abc import Callable
from pathlib import Path


def wait_until(check: Callable[[], bool], attempts: int, interval: float) -> bool:
    """Call ``check`` up to ``attempts`` times, ``interval`` seconds apart."""
    for attempt in range(attempts):
        if check():
            return True
        if attempt < attempts - 1:
            time.sleep(interval)
    return False


def sslip_name(ip: str) -> str:
    """A hostname that resolves to ``ip`` with no DNS setup at all."""
    return f"{ip.replace('.', '-')}.sslip.io"


def wait_for_host_key(ip: str, attempts: int = 60, interval: float = 5) -> bool:
    """Wait for sshd, then trust its host key (first use, as deploy-setup does).

    Providers recycle IPs, so a stale known_hosts entry for this address is
    dropped first; otherwise every later ssh fails on a changed host key.
    """
    subprocess.run(["ssh-keygen", "-R", ip], capture_output=True)
    keys: list[str] = []

    def scan() -> bool:
        result = subprocess.run(
            ["ssh-keyscan", "-T", "5", "-H", ip], capture_output=True, text=True
        )
        keys.append(result.stdout)
        return result.returncode == 0 and bool(result.stdout.strip())

    if not wait_until(scan, attempts, interval):
        return False
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    known_hosts.parent.mkdir(mode=0o700, exist_ok=True)
    with open(known_hosts, "a") as f:
        f.write(keys[-1])
    return True


def wait_for_dns(
    hostname: str, ip: str, attempts: int = 60, interval: float = 10
) -> bool:
    """Wait until ``hostname`` resolves to ``ip`` from here.

    Let's Encrypt rate-limits failed validations, so the first deploy waits
    for the name rather than letting Traefik ask for a certificate too early.
    """

    def resolves() -> bool:
        try:
            return socket.gethostbyname(hostname) == ip
        except OSError:
            return False

    return wait_until(resolves, attempts, interval)
