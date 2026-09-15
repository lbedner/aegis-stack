"""Tests for component file expansion, focused on skipping non-template files."""

from __future__ import annotations

from pathlib import Path

from aegis.core.component_files import (
    PROJECT_SLUG_PLACEHOLDER,
    _is_skippable_template_file,
    get_component_files,
    get_template_path,
)


class TestIsSkippableTemplateFile:
    """The walk must ignore tooling-cache dirs and binary artefacts."""

    def test_skips_pycache_dir(self) -> None:
        assert _is_skippable_template_file(
            Path("app/components/worker/__pycache__/broker.cpython-313.pyc")
        )

    def test_skips_compiled_python_anywhere(self) -> None:
        assert _is_skippable_template_file(Path("a/b/module.pyc"))
        assert _is_skippable_template_file(Path("module.pyo"))

    def test_skips_binary_assets(self) -> None:
        assert _is_skippable_template_file(Path("assets/logo.png"))
        assert _is_skippable_template_file(Path("assets/font.WOFF2"))

    def test_keeps_authored_python_and_jinja(self) -> None:
        assert not _is_skippable_template_file(Path("app/components/worker/broker.py"))
        assert not _is_skippable_template_file(Path("app/core/config.py.jinja"))
        assert not _is_skippable_template_file(
            Path("app/components/worker/__init__.py")
        )


class TestGetComponentFilesSkipsStrayArtefacts:
    """Regression: a stray ``.pyc`` in the template tree must not be returned.

    Importing a template's raw ``.py`` files compiles bytecode into a
    ``__pycache__`` beside them; the file walk used to include that ``.pyc``
    and the downstream UTF-8 renderer crashed reading it.
    """

    def test_pycache_excluded_from_worker_component(self) -> None:
        worker_dir = (
            get_template_path() / PROJECT_SLUG_PLACEHOLDER / "app/components/worker"
        )
        pycache = worker_dir / "__pycache__"
        stray = pycache / "broker_dramatiq.cpython-313.pyc"
        created_dir = not pycache.exists()
        pycache.mkdir(exist_ok=True)
        # Invalid UTF-8 byte that previously crashed the read_text() walk.
        stray.write_bytes(b"\xf3\x00\x01compiled")
        try:
            files = get_component_files("worker")
        finally:
            stray.unlink(missing_ok=True)
            if created_dir and pycache.exists() and not any(pycache.iterdir()):
                pycache.rmdir()

        assert not any("__pycache__" in f for f in files)
        assert not any(f.endswith(".pyc") for f in files)
        # Sanity: the real worker sources are still discovered.
        assert any(f.endswith("heartbeat.py") for f in files)


class TestAnotherSpecsGatedFilesAreNotYours:
    """Adding htmx to a project without auth must not write auth pages.

    The htmx component owns the whole ``web_frontend`` tree, and the auth
    service owns the login pages inside it - declared in auth's
    ``include_htmx`` extras bucket precisely so an htmx-without-auth
    project does not carry them. ``aegis init`` honours that; ``aegis add
    htmx`` copied the tree wholesale, leaving nine dead files nothing
    routes to.
    """

    AUTH_PAGES = "app/components/web_frontend/templates/pages/auth"
    AUTH_MACROS = "app/components/web_frontend/templates/components/auth_macros.html"

    def test_adding_htmx_without_auth_skips_the_auth_pages(self) -> None:
        files = get_component_files(
            "htmx", answers={"include_htmx": True, "include_auth": False}
        )

        assert not [f for f in files if f.startswith(self.AUTH_PAGES)]
        assert self.AUTH_MACROS not in files

    def test_adding_htmx_with_auth_keeps_them(self) -> None:
        files = get_component_files(
            "htmx", answers={"include_htmx": True, "include_auth": True}
        )

        assert [f for f in files if f.startswith(self.AUTH_PAGES)]

    def test_the_rest_of_the_frontend_comes_either_way(self) -> None:
        """Only the auth-owned subset is conditional."""
        without = get_component_files(
            "htmx", answers={"include_htmx": True, "include_auth": False}
        )

        assert [f for f in without if "web_frontend" in f]
