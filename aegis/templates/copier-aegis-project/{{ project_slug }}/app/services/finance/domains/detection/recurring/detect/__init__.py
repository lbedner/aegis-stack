"""Finding the recurring streams hiding in a transaction history.

Split by stage - ``shared`` for what a candidate is, ``streams`` for
writing one down, ``purge`` for retiring what no longer holds, ``run``
for the pass that uses all three.

``_resolve_payee_key`` is re-exported because callers import it from
here, as they did when this was one module; it belongs to
``payees`` and only passes through.
"""

from app.services.finance.domains.detection.recurring.detect.purge import (
    _purge_orphaned_proposals as _purge_orphaned_proposals,
)
from app.services.finance.domains.detection.recurring.detect.run import detect_recurring
from app.services.finance.domains.detection.recurring.detect.shared import (
    RecurringDetectionResult,
    candidate_filters,
)
from app.services.finance.domains.detection.recurring.detect.streams import (
    _inherited_curation as _inherited_curation,
)
from app.services.finance.domains.detection.recurring.detect.streams import (
    _upsert_stream as _upsert_stream,
)
from app.services.finance.domains.detection.recurring.resolve import (
    _resolve_payee_key as _resolve_payee_key,
)

__all__ = [
    "RecurringDetectionResult",
    "candidate_filters",
    "detect_recurring",
]
