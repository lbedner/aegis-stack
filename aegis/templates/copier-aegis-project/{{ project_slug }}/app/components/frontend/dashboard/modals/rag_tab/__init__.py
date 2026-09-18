"""The RAG tab, split by section.

``rag_tab.py`` was eight hundred lines: a tab, the four sections under
it, and the two cards those sections are made of. This re-exports the
names that were importable before, so nothing outside the package had
to change.
"""

from .collections_table import (
    CollectionRowCard,
    IndexedFileRow,
    RAGCollectionsTableSection,
)
from .panels import RAGConfigSection, RAGStatsSection
from .search_preview import SearchPreviewSection, SearchResultCard
from .tab import RAGTab

__all__ = [
    "CollectionRowCard",
    "IndexedFileRow",
    "RAGCollectionsTableSection",
    "RAGConfigSection",
    "RAGStatsSection",
    "RAGTab",
    "SearchPreviewSection",
    "SearchResultCard",
]
