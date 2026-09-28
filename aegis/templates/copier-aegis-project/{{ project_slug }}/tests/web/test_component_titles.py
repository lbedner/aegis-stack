"""One registry names components and services for every frontend."""

from app.components.web_frontend.overseer_nav import build_navigation
from app.services.system.ui import get_component_title


def test_overseer_titles_come_from_the_shared_registry() -> None:
    assert get_component_title("backend") == "Server"
    assert get_component_title("service_auth") == "Authentication"
    assert get_component_title("frontend") == "Flet Frontend"


def test_unknown_names_are_title_cased() -> None:
    assert get_component_title("my-plugin_thing") == "My Plugin Thing"
    assert get_component_title("service_my_plugin") == "My Plugin"


def test_navigation_uses_it() -> None:
    navigation = build_navigation(None)
    for entry in navigation["components"]:
        assert entry.title == get_component_title(entry.name)
    for entry in navigation["services"]:
        assert entry.title == get_component_title(f"service_{entry.name}")
