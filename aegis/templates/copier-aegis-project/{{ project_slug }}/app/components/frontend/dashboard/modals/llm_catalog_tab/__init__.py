"""The Cloud Catalog tab.

Only ships with a database backend - ``ai_modal`` imports it inside
a ``try/except ImportError`` and hides the tab when it is absent.
"""

from .tab import LLMCatalogTab

__all__ = ["LLMCatalogTab"]
