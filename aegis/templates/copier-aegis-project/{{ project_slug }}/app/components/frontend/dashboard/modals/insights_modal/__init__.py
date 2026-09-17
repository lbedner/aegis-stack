"""The Insights modal, split by tab.

Was a single 3,831-line module holding eight tabs, their shared chart
primitives and the dialog that arranges them. The names the old module
exposed are re-exported here, so importers do not care that it became a
package - the same move ``finance_modal`` made before it.
"""

from app.components.frontend.dashboard.modals.insights_modal.dialog import (
    InsightsDetailDialog,
)

__all__ = ["InsightsDetailDialog"]
