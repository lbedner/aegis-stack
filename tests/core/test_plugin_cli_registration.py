"""
Plugin CLI verb registration in the generated project's ``app/cli/main.py``.

A plugin declaring ``cli_name`` ships an ``app/cli/<cli_name>.py`` module
exposing a typer ``app``; the generated project's CLI entrypoint registers
it via ``app.add_typer(...)`` so ``<project> <cli_name> ...`` works the
same way the in-tree ``auth`` / ``llm`` subcommands do.

``app/cli/main.py`` is a shared file — no component/service manifest
claims it, so it falls into the render-diff engine's scope automatically
(``get_shared_scope``) and the block below re-renders whenever a plugin is
added or removed.
"""

from __future__ import annotations

import ast

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_template_path
from aegis.core.plugins.composer import PLUGINS_ANSWER_KEY, serialize_plugin_to_answer
from aegis.core.plugins.spec import PluginKind, PluginSpec

CLI_MAIN = "app/cli/main.py"
PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _render(context: dict) -> str:
    """Render ``app/cli/main.py`` the way ``ManualUpdater`` does."""
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())),
        trim_blocks=False,
        lstrip_blocks=False,
    )
    template = env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/{CLI_MAIN}.jinja")
    return template.render(context)


def _plugin(name: str, cli_name: str | None) -> dict:
    spec = PluginSpec(
        name=name,
        kind=PluginKind.SERVICE,
        description="x",
        version="0.1.0",
        verified=False,
        cli_name=cli_name,
    )
    return serialize_plugin_to_answer(spec)


class TestPluginCliRegistration:
    def test_registers_declared_verb(self) -> None:
        out = _render({PLUGINS_ANSWER_KEY: [_plugin("crawl4ai", "crawl")]})
        assert 'importlib.import_module("app.cli.crawl")' in out
        assert 'name="crawl"' in out

    def test_verb_is_decoupled_from_install_name(self) -> None:
        """The plugin installs as ``crawl4ai`` but the verb is ``crawl``."""
        out = _render({PLUGINS_ANSWER_KEY: [_plugin("crawl4ai", "crawl")]})
        assert 'importlib.import_module("app.cli.crawl4ai")' not in out

    def test_plugin_without_cli_name_registers_nothing(self) -> None:
        out = _render({PLUGINS_ANSWER_KEY: [_plugin("metrics", None)]})
        assert "app.cli.metrics" not in out

    def test_no_plugins_renders_clean(self) -> None:
        """The default (no plugins) render must be unaffected."""
        out = _render({})
        assert "importlib.import_module" in out  # in-tree registrations intact
        assert "app.cli.crawl" not in out

    def test_hyphenated_verb_yields_valid_identifier(self) -> None:
        """``cli_name`` may contain hyphens; the local variable may not."""
        out = _render({PLUGINS_ANSWER_KEY: [_plugin("web-scraper", "web-scrape")]})
        assert 'name="web-scrape"' in out
        assert "web-scrape_module" not in out
        assert "web_scrape_module" in out

    def test_hyphenated_verb_imports_a_valid_module_path(self) -> None:
        """The dotted path must be normalized too, not just the variable.

        ``app.cli.web-scrape`` is not an importable name, and the failure
        mode is silent: ``import_module`` raises ``ModuleNotFoundError``,
        a subclass of the ``ImportError`` the generated block catches, so
        the plugin's CLI would vanish with no signal.
        """
        out = _render({PLUGINS_ANSWER_KEY: [_plugin("web-scraper", "web-scrape")]})
        assert 'importlib.import_module("app.cli.web_scrape")' in out
        assert "app.cli.web-scrape" not in out

    def test_multiple_plugins_each_register(self) -> None:
        out = _render(
            {
                PLUGINS_ANSWER_KEY: [
                    _plugin("crawl4ai", "crawl"),
                    _plugin("reporter", "report"),
                ]
            }
        )
        assert 'name="crawl"' in out
        assert 'name="report"' in out


class TestRenderedFileIsValidPython:
    """Whatever the plugin loop emits has to parse; a syntax error here
    breaks the generated project's entire CLI."""

    def test_parses_with_plugin(self) -> None:
        ast.parse(_render({PLUGINS_ANSWER_KEY: [_plugin("crawl4ai", "crawl")]}))

    def test_parses_without_plugins(self) -> None:
        ast.parse(_render({}))

    def test_parses_with_multiple_plugins(self) -> None:
        ast.parse(
            _render(
                {
                    PLUGINS_ANSWER_KEY: [
                        _plugin("crawl4ai", "crawl"),
                        _plugin("reporter", "report"),
                    ]
                }
            )
        )
