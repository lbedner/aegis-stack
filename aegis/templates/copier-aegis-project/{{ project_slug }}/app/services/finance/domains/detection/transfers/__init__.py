"""Internal-transfer detection, split by how a pair is found.

``detect`` runs the passes in order; each sibling is one pass, and
``shared`` holds the thresholds they all score against.
"""

from .detect import detect_transfers
from .shared import AUTO_THRESHOLD, WINDOW_DAYS, TransferDetectionResult

__all__ = [
    "AUTO_THRESHOLD",
    "WINDOW_DAYS",
    "TransferDetectionResult",
    "detect_transfers",
]
