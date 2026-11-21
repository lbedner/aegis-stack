"""What one catalog sync did.

Its own module because both the service and the row writers it
delegates to tally into it.
"""

from dataclasses import dataclass, field, fields
from typing import Self


@dataclass
class SyncResult:
    """Result of an LLM catalog sync operation."""

    vendors_added: int = 0
    vendors_updated: int = 0
    models_added: int = 0
    models_updated: int = 0
    deployments_synced: int = 0
    prices_synced: int = 0
    modalities_synced: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: Self) -> None:
        """Another sync's tally (the engine's, the speech server's) added in."""
        for f in fields(self):
            if f.type is int:
                setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))
        self.errors.extend(other.errors)

    @property
    def total_synced(self) -> int:
        """Total number of records synced."""
        return (
            self.vendors_added
            + self.vendors_updated
            + self.models_added
            + self.models_updated
        )
