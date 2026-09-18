"""The blog modal, split by tab.

Was a single 1,432-line module. ``modal_registry`` and the modals
package both import BlogDetailDialog from here, and neither changed.
"""

from app.components.frontend.dashboard.modals.blog_modal.dialog import (
    BlogDetailDialog,
)

__all__ = ["BlogDetailDialog"]
