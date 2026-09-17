"""Cached payloads are namespaced by the build that produced them.

A cached bulk payload is served for as long as its TTL allows, and its key
used to describe only the data. Change the shape of a response, or a
threshold behind a computed field, and the old entry is wrong even though
the rows behind it never moved: the app keeps serving it until the TTL
expires. Keying on the deployed commit means new code cannot read what old
code wrote, and the orphans age out on their own.

The value is stamped into the server's ``.env`` by ``aegis deploy``; see
``tests/cli/test_deploy_helpers.py`` for that half.
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _render(path: str, **overrides: Any) -> str:
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())),
        keep_trailing_newline=True,
    )
    ctx = {**get_copier_defaults(), "project_slug": "demo_app", **overrides}
    return env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/{path}").render(ctx)


def _constants() -> str:
    return (
        get_template_path()
        / PROJECT_SLUG_PLACEHOLDER
        / "app/services/insights/constants.py"
    ).read_text()


class TestTheSettingExists:
    def test_config_carries_a_build_id(self) -> None:
        rendered = _render("app/core/config.py.jinja")
        assert 'BUILD_ID: str = "dev"' in rendered

    def test_the_env_example_documents_it(self) -> None:
        assert "BUILD_ID=dev" in _render(".env.example.jinja")


class TestTheKeysCarryIt:
    def test_both_builders_namespace_on_the_build(self) -> None:
        source = _constants()
        assert "def all_insights_key()" in source
        assert "def project_insights_key(" in source
        # Read at call time: binding at import freezes the value for the
        # process and makes it untestable.
        assert source.count("from app.core.config import settings") == 2

    def test_the_endpoint_and_the_collector_share_the_builders(self) -> None:
        """The same key was spelled out in both places before, which is
        exactly how a cache write and its invalidation drift apart."""
        on = {
            "include_database": True,
            "include_insights": True,
            "insights_per_user": True,
        }
        endpoint = _render("app/components/backend/api/insights.py.jinja", **on)
        collector = _render(
            "app/services/insights/adapters/collectors/collection.py.jinja", **on
        )

        for source in (endpoint, collector):
            assert "all_insights_key()" in source
            assert "project_insights_key(" in source
            assert '"insights:all"' not in source
            assert 'f"insights:project:' not in source
