"""A plugin names itself once, in health metadata, and every dashboard
surface honours it.

A plugin is not in the component registry the stack view and the
architecture diagram look their labels up in, so both fell back to the
raw health id: the stack view showed a blank description and the diagram
showed "Service Crawler" for a crawl4ai plugin. The convention a health
check follows is to put ``subtitle`` (and optionally ``version``) in its
metadata; these are the surfaces that have to read it.
"""

from app.components.frontend.dashboard.diagram.diagram_node import DiagramNode
from app.components.frontend.dashboard.status_overview import (
    get_component_display_info,
)
from app.services.system.models import ComponentStatus, ComponentStatusType
from app.services.system.ui import get_component_subtitle

PLUGIN_ID = "service_Crawler"
PLUGIN_METADATA = {"subtitle": "Crawl4AI", "version": "0.9.3"}


def _status(metadata: dict[str, object]) -> ComponentStatus:
    return ComponentStatus(
        name="Crawler",
        status=ComponentStatusType.HEALTHY,
        message="OK",
        metadata=metadata,
    )


def test_helper_prefers_the_name_health_metadata_declares() -> None:
    assert get_component_subtitle(PLUGIN_ID, PLUGIN_METADATA) == "Crawl4AI 0.9.3"


def test_helper_falls_back_to_the_registry_label() -> None:
    """An in-tree component names nothing in metadata and is unaffected."""
    assert get_component_subtitle("cache", {}) == "Redis"


def test_stack_view_shows_the_declared_name() -> None:
    title, subtitle = get_component_display_info(PLUGIN_ID, _status(PLUGIN_METADATA))
    assert title == "Crawler"
    assert subtitle == "Crawl4AI 0.9.3"


def test_diagram_shows_the_declared_name() -> None:
    # ``_get_subtitle`` reads only its arguments, so it needs no node.
    subtitle = DiagramNode._get_subtitle(None, PLUGIN_ID, _status(PLUGIN_METADATA))
    assert subtitle == "Crawl4AI 0.9.3"


def test_surfaces_agree_without_a_version() -> None:
    status = _status({"subtitle": "Crawl4AI"})
    assert get_component_display_info(PLUGIN_ID, status)[1] == "Crawl4AI"
    assert DiagramNode._get_subtitle(None, PLUGIN_ID, status) == "Crawl4AI"


def test_plugin_with_no_declared_name_never_shows_the_raw_id() -> None:
    status = _status({})
    title, subtitle = get_component_display_info(PLUGIN_ID, status)
    assert title == "Crawler"
    assert "service_" not in subtitle
    assert "service_" not in DiagramNode._get_subtitle(None, PLUGIN_ID, status)
