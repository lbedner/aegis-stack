"""Secret tokens a machine shows the app instead of a session (an MCP
client, a meeting runner): minted once, shown once, kept only as a digest,
with a short hint to tell them apart."""

from dataclasses import dataclass
import hashlib
import secrets


@dataclass(frozen=True)
class Minted:
    value: str
    digest: str
    hint: str


def mint(prefix: str) -> Minted:
    """A new token starting ``prefix``: its value (to show once), and the
    digest and hint to keep."""
    value = prefix + secrets.token_urlsafe(32)
    return Minted(value, digest(value), value[: len(prefix) + 4])


def digest(value: str) -> str:
    """What is kept of a token, and looked up by."""
    return hashlib.sha256(value.encode()).hexdigest()
