"""The backend modal's Cache tab: the same view as the htmx Server page's
Cache section, built by the same helper (``app.services.system.ui_cache``)."""

from app.core.cache import CacheEntry, CacheStats
from app.services.system import ui_cache
from tests.components.frontend._tree import texts as _texts


def _tab(view: dict) -> object:
    from app.components.frontend.dashboard.modals.backend_modal.cache_tab import (
        CacheTab,
    )

    tab = CacheTab()
    tab._render(view)
    return tab


def test_families_and_largest_keys_are_shown() -> None:
    view = {"error": None} | ui_cache.summarize(
        "redis",
        [
            CacheEntry("insights:project:1", 4000, 200),
            CacheEntry("llm:price:gpt-4o", 100, 50),
        ],
        False,
        {"insights:project": CacheStats(hits=3, misses=1)},
    )
    shown = _texts(_tab(view))
    assert "insights:project" in shown
    assert "insights:project:1" in shown
    assert "75.0%" in shown


def test_an_empty_cache_says_so() -> None:
    view = {"error": None} | ui_cache.summarize("memory", [], False, {})
    assert any("empty" in t.lower() for t in _texts(_tab(view)))


def test_an_unreadable_cache_says_why() -> None:
    shown = _texts(_tab({"error": "redis down", "backend": "redis"}))
    assert any("redis down" in t for t in shown)
