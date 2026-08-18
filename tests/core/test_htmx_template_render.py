"""Render-time guards for the htmx web frontend gating (HF-03).

Flet is CORE and always present: every test here also asserts the Flet
wiring is untouched, because the one thing this gate must never do is
gate Flet. With ``include_htmx`` off the rendered output carries no htmx
trace at all; with it on, the htmx side (deps, the ``/`` mount, the
``/static`` mount, health wiring, config) appears alongside Flet.

The template tree itself lands in HF-04; HF-03 ships the gate plus a stub
route so the mount is real.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"

# The property is "Flet owns /dashboard", not what the local is called.
FLET_MOUNT = 'app.mount("/dashboard"'


def _env() -> Environment:
    # keep_trailing_newline mirrors Copier's own default (copier/_template.py),
    # so a render here matches what a generated project actually receives.
    return Environment(
        loader=FileSystemLoader(str(get_template_path())),
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )


def _render(path: str, context: dict[str, Any]) -> str:
    return _env().get_template(f"{PROJECT_SLUG_PLACEHOLDER}/{path}").render(context)


def _ctx(**overrides: Any) -> dict[str, Any]:
    return {**get_copier_defaults(), "include_htmx": False, **overrides}


def _blank_lines_between(rendered: str, first: str, second: str) -> int:
    """Blank lines separating the first line containing ``first`` from the
    next line containing ``second``.

    Anchored on the gate's actual property - adjacency - rather than on the
    full import statements. Matching those verbatim made this test fail the
    moment the imports grew a ``# noqa`` comment, which says nothing about
    whitespace control and everything about the anchor being too literal.
    """
    lines = rendered.split("\n")
    start = next(i for i, line in enumerate(lines) if first in line)
    end = next(
        i for i, line in enumerate(lines[start + 1 :], start + 1) if second in line
    )
    return sum(1 for line in lines[start + 1 : end] if not line.strip())


class TestHtmxOffLeavesNoTrace:
    """The default project must render exactly as it did pre-HF-03."""

    def test_main_has_no_htmx_mount(self) -> None:
        rendered = _render("app/integrations/main.py.jinja", _ctx())
        assert "web_frontend" not in rendered
        assert "htmx" not in rendered.lower()

    def test_main_keeps_flet_wiring(self) -> None:
        rendered = _render("app/integrations/main.py.jinja", _ctx())
        assert FLET_MOUNT in rendered
        assert "await flet_fastapi.app_manager.start()" in rendered
        assert "create_frontend_app()" in rendered

    def test_pyproject_has_no_htmx_deps(self) -> None:
        rendered = _render("pyproject.toml.jinja", _ctx())
        assert "jinja2" not in rendered.lower()

    def test_pyproject_keeps_flet_unconditional(self) -> None:
        # Version-agnostic on purpose: a flet bump is not an htmx regression.
        rendered = _render("pyproject.toml.jinja", _ctx())
        assert '"flet[all]' in rendered

    def test_config_has_no_htmx_settings(self) -> None:
        rendered = _render("app/core/config.py.jinja", _ctx())
        assert "WEB_TEMPLATES_DIR" not in rendered
        assert "WEB_STATIC_DIR" not in rendered

    def test_config_keeps_flet_assets_dir(self) -> None:
        rendered = _render("app/core/config.py.jinja", _ctx())
        assert "FLET_ASSETS_DIR:" in rendered

    def test_health_has_no_web_frontend_entry(self) -> None:
        rendered = _render(
            "app/components/backend/startup/component_health.py.jinja", _ctx()
        )
        assert "web_frontend" not in rendered

    def test_health_keeps_flet_frontend_check(self) -> None:
        rendered = _render(
            "app/components/backend/startup/component_health.py.jinja", _ctx()
        )
        assert "_frontend_component_health" in rendered

    def test_ui_label_is_flet_only(self) -> None:
        rendered = _render("app/services/system/ui.py.jinja", _ctx())
        assert '"frontend": "Flet",' in rendered
        assert "htmx" not in rendered.lower()

    def test_import_gate_is_whitespace_controlled(self) -> None:
        """A ``{% if %}`` without the ``-`` leaves a blank line behind when
        the gate is off, so the default project would diff against every
        already-generated one. The import gate is the check: with htmx off
        the two imports it sits between must stay adjacent.
        """
        rendered = _render("app/integrations/main.py.jinja", _ctx())
        assert (
            _blank_lines_between(
                rendered, "import create_frontend_app", "from app.core.config import"
            )
            == 0
        )


class TestHtmxOnAddsWebFrontend:
    """``include_htmx`` adds the htmx side without disturbing Flet."""

    def test_main_mounts_htmx_router_at_root(self) -> None:
        rendered = _render("app/integrations/main.py.jinja", _ctx(include_htmx=True))
        assert "web_frontend" in rendered
        assert "include_router" in rendered

    def test_import_gate_is_whitespace_controlled(self) -> None:
        """Mirror of the htmx-off case: the gated import block slots between
        its neighbours without opening a blank line on either side."""
        rendered = _render("app/integrations/main.py.jinja", _ctx(include_htmx=True))
        assert (
            _blank_lines_between(
                rendered,
                "import create_frontend_app",
                "from app.components.web_frontend",
            )
            == 0
        )
        assert (
            _blank_lines_between(
                rendered,
                "from app.components.web_frontend",
                "from app.core.config import",
            )
            == 0
        )

    def test_main_mounts_static(self) -> None:
        rendered = _render("app/integrations/main.py.jinja", _ctx(include_htmx=True))
        assert '"/static"' in rendered

    def test_main_keeps_flet_dashboard_mount(self) -> None:
        """The exact Pulse layout: htmx at /, Overseer still at /dashboard."""
        rendered = _render("app/integrations/main.py.jinja", _ctx(include_htmx=True))
        assert FLET_MOUNT in rendered
        assert "await flet_fastapi.app_manager.start()" in rendered

    def test_pyproject_adds_jinja2(self) -> None:
        rendered = _render("pyproject.toml.jinja", _ctx(include_htmx=True))
        assert "jinja2" in rendered.lower()

    def test_pyproject_adds_multipart(self) -> None:
        rendered = _render("pyproject.toml.jinja", _ctx(include_htmx=True))
        assert "python-multipart" in rendered

    def test_pyproject_multipart_not_duplicated_when_auth_also_on(self) -> None:
        """auth already pulls python-multipart; htmx must extend that gate,
        not emit a second pin (a duplicate dep breaks uv resolution)."""
        rendered = _render(
            "pyproject.toml.jinja", _ctx(include_htmx=True, include_auth=True)
        )
        assert rendered.count("python-multipart==") == 1

    def test_config_adds_htmx_dirs_and_keeps_flet(self) -> None:
        rendered = _render("app/core/config.py.jinja", _ctx(include_htmx=True))
        assert "WEB_TEMPLATES_DIR" in rendered
        assert "WEB_STATIC_DIR" in rendered
        assert "FLET_ASSETS_DIR:" in rendered

    def test_health_registers_web_frontend(self) -> None:
        rendered = _render(
            "app/components/backend/startup/component_health.py.jinja",
            _ctx(include_htmx=True),
        )
        assert 'register_health_check("web_frontend"' in rendered

    def test_health_web_frontend_checks_templates_and_manifest(self) -> None:
        rendered = _render(
            "app/components/backend/startup/component_health.py.jinja",
            _ctx(include_htmx=True),
        )
        assert "manifest.json" in rendered
        assert "WEB_TEMPLATES_DIR" in rendered

    def test_ui_label_mentions_both_frontends(self) -> None:
        rendered = _render("app/services/system/ui.py.jinja", _ctx(include_htmx=True))
        assert "htmx" in rendered.lower()
        # Flet is still named — the label describes both, not htmx alone.
        assert "Flet" in rendered


GATED_PYTHON_TEMPLATES = [
    "app/integrations/main.py.jinja",
    "app/core/config.py.jinja",
    "app/components/backend/startup/component_health.py.jinja",
    "app/services/system/ui.py.jinja",
]


@pytest.mark.parametrize("path", GATED_PYTHON_TEMPLATES)
@pytest.mark.parametrize("include_htmx", [False, True])
def test_gated_templates_render_valid_python(path: str, include_htmx: bool) -> None:
    """Both sides of every htmx gate must parse.

    A misplaced ``{%- if %}`` yields output that still contains the right
    strings but no longer compiles; only parsing catches that.
    """
    ast.parse(_render(path, _ctx(include_htmx=include_htmx)))


def test_web_frontend_modules_are_valid_python() -> None:
    """The tree ships as plain .py (copied verbatim, not Copier-rendered),
    so nothing else parses it before a generated project imports it."""
    root = _web_frontend_tree()
    for source in sorted(root.rglob("*.py")):
        ast.parse(source.read_text(), filename=str(source))


class TestWebFrontendCleanup:
    """With htmx off the tree is deleted; the Flet frontend is never touched.

    Deletion rides the spec's ``FileManifest`` through post-gen's Pattern A
    loop, so there is no htmx-specific branch in ``cleanup_components``.
    """

    def test_spec_manifest_owns_the_web_frontend_tree(self) -> None:
        from aegis.core.components import COMPONENTS

        assert "app/components/web_frontend" in COMPONENTS["htmx"].files.primary

    def test_spec_manifest_never_claims_the_flet_tree(self) -> None:
        from aegis.core.components import COMPONENTS

        for path in COMPONENTS["htmx"].files.primary:
            assert not path.startswith("app/components/frontend")

    def test_cleanup_deletes_web_frontend_when_off(self, tmp_path: Any) -> None:
        from aegis.core.post_gen_tasks import cleanup_components

        web = tmp_path / "app" / "components" / "web_frontend"
        web.mkdir(parents=True)
        (web / "router.py").write_text("stub")
        flet = tmp_path / "app" / "components" / "frontend"
        flet.mkdir(parents=True)
        (flet / "main.py").write_text("flet")

        cleanup_components(tmp_path, {"include_htmx": False})

        assert not web.exists()
        assert (flet / "main.py").read_text() == "flet"

    def test_cleanup_keeps_web_frontend_when_on(self, tmp_path: Any) -> None:
        from aegis.core.post_gen_tasks import cleanup_components

        web = tmp_path / "app" / "components" / "web_frontend"
        web.mkdir(parents=True)
        (web / "router.py").write_text("stub")

        cleanup_components(tmp_path, {"include_htmx": True})

        assert (web / "router.py").read_text() == "stub"


def _web_frontend_tree() -> Path:
    return (
        get_template_path() / PROJECT_SLUG_PLACEHOLDER / "app/components/web_frontend"
    )


class TestWebFrontendScaffolding:
    """The shape the web_frontend tree ships in.

    Runtime behaviour (static() resolution, cache headers, the index route)
    is covered inside the generated project by
    ``tests/components/test_web_frontend.py``, where the code is importable.
    These pin what ships, and that the port stayed generic.
    """

    def test_ships_scaffolding_modules(self) -> None:
        root = _web_frontend_tree()
        for rel in (
            "__init__.py",
            "main.py",
            "routes/__init__.py",
            # Gated: the auth handlers only exist when the auth service does.
            "routes/pages.py.jinja",
            # Empty package on purpose: it establishes the htmx-fragment
            # convention before there are fragments to put in it.
            "routes/partials/__init__.py",
        ):
            assert (root / rel).is_file(), rel

    def test_ships_template_and_static_asset(self) -> None:
        root = _web_frontend_tree()
        for rel in (
            "templates/base.html",
            "templates/pages/landing.html",
            "templates/components/snackbar.html",
            "templates/components/macros.html",
            "templates/components/landing/navbar.html",
            "templates/components/landing/hero.html",
            "templates/components/landing/features.html",
            "templates/components/landing/footer.html",
            "static/css/app.css",
            "static/js/app.js",
            "static/favicon.svg",
        ):
            assert (root / rel).is_file(), rel

    def test_macro_kit_is_the_generic_set(self) -> None:
        """Only the reusable macros came across; Pulse's insights and
        dashboard macros stayed behind."""
        import re

        source = (_web_frontend_tree() / "templates/components/macros.html").read_text()
        defined = set(re.findall(r"{%-?\s*macro\s+(\w+)\(", source))
        assert defined == {
            "modal_scrim",
            "popover_panel",
            "hover_hint",
            "info_tooltip",
            "primary_button",
            "submit_button",
            "select_field",
            "password_input",
            "or_divider",
        }

    def test_base_layout_declares_the_block_structure(self) -> None:
        source = (_web_frontend_tree() / "templates/base.html").read_text()
        for block in (
            "title",
            "favicon",
            "head_extra",
            "navbar",
            "page_body",
            "content",
            "footer",
            "scripts",
        ):
            assert f"{{% block {block} %}}" in source, block

    def test_main_is_valid_python(self) -> None:
        ast.parse((_web_frontend_tree() / "main.py").read_text())

    def test_base_layout_resolves_assets_through_static_global(self) -> None:
        """Assets go through static() so they pick up fingerprinted URLs once
        an asset build exists, rather than being hardcoded."""
        html = (_web_frontend_tree() / "templates/base.html").read_text()
        for asset in ("css/app.css", "js/app.js", "favicon.svg", "dist/app.css"):
            assert f"static('{asset}')" in html, asset

    def test_landing_extends_the_base_layout(self) -> None:
        html = (_web_frontend_tree() / "templates/pages/landing.html").read_text()
        assert '{% extends "base.html" %}' in html

    def test_landing_is_composed_from_includes(self) -> None:
        html = (_web_frontend_tree() / "templates/pages/landing.html").read_text()
        for part in ("navbar", "hero", "features", "footer"):
            assert f'{{% include "components/landing/{part}.html" %}}' in html, part

    def test_landing_copy_comes_from_copier_answers(self) -> None:
        """No hardcoded product copy: the name and description are the
        project's own, so a fresh project reads as itself."""
        root = _web_frontend_tree() / "templates"
        hero = (root / "components/landing/hero.html").read_text()
        assert "{{ project_name }}" in hero
        assert "{{ project_description }}" in hero

    def test_port_is_de_pulsed(self) -> None:
        """The scaffolding is generic: Pulse's product-specific globals,
        filters and routes must not have come across with it.
        """
        source = (_web_frontend_tree() / "main.py").read_text().lower()
        for banned in (
            "plausible",
            "docs_url",
            "markdown",
            "nh3",
            "onboarding",
            "genesis",
            "stack_meta",
            "country_flag",
            "chip_label",
            # localdt needs a user model; it lands behind the auth gate.
            "localdt",
        ):
            assert banned not in source, banned


class TestNodePipeline:
    """The Tailwind/DaisyUI/Biome pipeline (HF-07).

    Tailwind is precompiled, never CDN-JIT, so these pin the pieces that
    make an ahead-of-time build possible and correct.
    """

    def _root(self) -> Path:
        return get_template_path() / PROJECT_SLUG_PLACEHOLDER

    def test_package_json_pins_the_proven_versions(self) -> None:
        """Tailwind must stay on 3.x: the DaisyUI 4 pairing is what is
        proven, and Tailwind 4 changes the config format entirely."""
        import json

        rendered = _render("package.json.jinja", _ctx(include_htmx=True))
        pkg = json.loads(rendered)
        assert pkg["devDependencies"]["tailwindcss"].startswith("3.")
        assert pkg["devDependencies"]["daisyui"].startswith("4.")
        assert pkg["private"] is True
        # devDeps only: this is a build tool, not a JS app.
        assert "dependencies" not in pkg

    def test_package_json_names_this_project(self) -> None:
        import json

        rendered = _render(
            "package.json.jinja", _ctx(include_htmx=True, project_slug="demo")
        )
        assert json.loads(rendered)["name"] == "demo-css"

    def test_build_script_writes_minified_css_where_static_looks(self) -> None:
        """The build output path must match what static()/base.html expect,
        or the page silently loads nothing."""
        import json

        pkg = json.loads(_render("package.json.jinja", _ctx(include_htmx=True)))
        build = pkg["scripts"]["build"]
        assert "app/components/web_frontend/static/input.css" in build
        assert "app/components/web_frontend/static/dist/app.css" in build
        assert "--minify" in build
        assert "--watch" in pkg["scripts"]["watch"]

    def test_tailwind_content_globs_cover_the_shipped_markup(self) -> None:
        """A class Tailwind cannot see is a class it does not emit."""
        source = (self._root() / "tailwind.config.js").read_text()
        assert "./app/components/web_frontend/templates/**/*.html" in source
        assert "./app/components/web_frontend/static/js/**/*.js" in source

    def test_tailwind_theme_carries_the_brand_palette(self) -> None:
        source = (self._root() / "tailwind.config.js").read_text()
        assert "#17CCBF" in source  # brand teal
        assert "daisyui" in source
        assert "aegis:" in source  # the DaisyUI theme name base.html asks for

    def test_base_layout_requests_the_daisyui_theme(self) -> None:
        html = (_web_frontend_tree() / "templates/base.html").read_text()
        assert 'data-theme="aegis"' in html

    def test_input_css_pulls_in_tailwind_layers(self) -> None:
        source = (_web_frontend_tree() / "static/input.css").read_text()
        for layer in (
            "@tailwind base;",
            "@tailwind components;",
            "@tailwind utilities;",
        ):
            assert layer in source, layer
        assert "@layer components" in source

    def test_biome_never_runs_unscoped(self) -> None:
        """Biome with no path walks the whole project and rewrites every .js
        it finds — including the docs scripts, which are not ours. post-gen
        runs `make fix`, so an unscoped invocation reformats a user's files
        the moment their project is generated.
        """
        import json
        import re

        makefile = _render("Makefile.jinja", _ctx(include_htmx=True))
        for line in makefile.splitlines():
            if "biome" not in line:
                continue
            assert "$(WEB_JS_DIR)" in line, f"unscoped biome: {line.strip()}"

        pkg = json.loads(_render("package.json.jinja", _ctx(include_htmx=True)))
        for name, script in pkg["scripts"].items():
            if "biome" not in script:
                continue
            assert re.search(r"web_frontend/static/js", script), (
                f"unscoped biome in npm script {name!r}: {script}"
            )

    def test_makefile_frontend_targets_are_htmx_only(self) -> None:
        on = _render("Makefile.jinja", _ctx(include_htmx=True))
        for target in ("build-static:", "lint-frontend:", "format-frontend:"):
            assert target in on, target

        off = _render("Makefile.jinja", _ctx())
        for target in ("build-static:", "lint-frontend:", "format-frontend:"):
            assert target not in off, target
        assert "biome" not in off.lower()
        assert "djlint" not in off.lower()

    def test_gitignore_excludes_node_output_only_for_htmx(self) -> None:
        on = _render(".gitignore.jinja", _ctx(include_htmx=True))
        assert "node_modules/" in on
        assert "app/components/web_frontend/static/dist/" in on

        off = _render(".gitignore.jinja", _ctx())
        assert "node_modules/" not in off

    def test_build_static_fingerprints_after_compiling(self) -> None:
        """Compile then fingerprint: hashing before Tailwind writes would
        fingerprint the previous CSS."""
        rendered = _render("Makefile.jinja", _ctx(include_htmx=True))
        target = rendered.split("build-static:", 1)[1].split("\n\n", 1)[0]
        assert "npm run build" in target
        assert "python -m app.components.web_frontend.build" in target
        assert target.index("npm run build") < target.index(
            "python -m app.components.web_frontend.build"
        )

    def test_fingerprinting_modules_ship(self) -> None:
        root = _web_frontend_tree()
        assert (root / "build.py").is_file()
        assert (root / "build_watch.py").is_file()

    def test_watchdog_is_available_to_htmx_projects(self) -> None:
        """The watcher imports watchdog; without the dep the dev service
        dies on import."""
        assert "watchdog" in _render("pyproject.toml.jinja", _ctx(include_htmx=True))
        # And it still ships for worker-only projects, which had it first.
        assert "watchdog" in _render("pyproject.toml.jinja", _ctx(include_worker=True))

    def test_entrypoint_dispatches_build_watch_only_for_htmx(self) -> None:
        on = _render("scripts/entrypoint.sh.jinja", _ctx(include_htmx=True))
        assert '"$run_command" = "build-watch"' in on
        assert "build_watch" in on

        off = _render("scripts/entrypoint.sh.jinja", _ctx())
        assert "build-watch" not in off

    def test_pipeline_files_are_owned_by_the_manifest(self) -> None:
        """package.json and tailwind.config.js carry no Jinja gate of their
        own, so post-gen cleanup is the only thing keeping them out of
        non-htmx projects."""
        from aegis.core.components import COMPONENTS

        primary = COMPONENTS["htmx"].files.primary
        assert "package.json" in primary
        assert "tailwind.config.js" in primary


class TestDockerAndComposeWiring:
    """The Docker CSS story (HF-09).

    CSS is baked at image build so no Node reaches the runtime layer; two
    dev-only services give hot rebuild instead.
    """

    def test_css_build_stage_compiles_ahead_of_time(self) -> None:
        rendered = _render("Dockerfile.jinja", _ctx(include_htmx=True))
        assert "FROM node:22-alpine AS css-build" in rendered
        assert "npx tailwindcss" in rendered
        assert "--minify" in rendered

    def test_runtime_layer_has_no_node(self) -> None:
        """The whole point of a separate stage: the shipped image runs
        Python only."""
        rendered = _render("Dockerfile.jinja", _ctx(include_htmx=True))
        runtime = rendered.split("FROM python:", 1)[1]
        assert "npm " not in runtime
        assert "npx " not in runtime
        assert "node:" not in runtime

    def test_runtime_overlays_css_then_fingerprints_it(self) -> None:
        """Order matters: fingerprinting before the overlay would hash the
        absent (or stale) stylesheet."""
        rendered = _render("Dockerfile.jinja", _ctx(include_htmx=True))
        overlay = rendered.index("COPY --from=css-build")
        fingerprint = rendered.index("RUN python -m app.components.web_frontend.build")
        assert overlay < fingerprint

    def test_css_build_scans_the_sources_tailwind_needs(self) -> None:
        """Tailwind only emits classes it can see; a source missing from
        the stage silently drops styles from the image."""
        rendered = _render("Dockerfile.jinja", _ctx(include_htmx=True))
        stage = rendered.split("FROM python:", 1)[0]
        for needed in (
            "package.json",
            "tailwind.config.js",
            "app/components/web_frontend/static/input.css",
            "app/components/web_frontend/templates",
            "app/components/web_frontend/static/js",
        ):
            assert needed in stage, needed

    def test_dockerfile_untouched_without_htmx(self) -> None:
        rendered = _render("Dockerfile.jinja", _ctx())
        assert "css-build" not in rendered
        assert "node" not in rendered.lower()
        assert "web_frontend" not in rendered
        # Still a single-stage Python image.
        assert rendered.count("FROM ") == 1

    def test_dev_compose_runs_both_watchers(self) -> None:
        rendered = _render("docker-compose.dev.yml.jinja", _ctx(include_htmx=True))
        assert "tailwind:" in rendered
        assert "build-static-watcher:" in rendered
        # The chain that makes hot reload work: tailwind rewrites app.css,
        # the watcher re-fingerprints it.
        assert "--watch=always" in rendered
        assert "build-watch" in rendered

    def test_dev_tailwind_service_polls_for_docker_fs_events(self) -> None:
        """Docker bind mounts don't deliver inotify events on macOS or
        Windows; without polling the watcher never fires."""
        rendered = _render("docker-compose.dev.yml.jinja", _ctx(include_htmx=True))
        assert 'CHOKIDAR_USEPOLLING: "true"' in rendered
        assert 'CHOKIDAR_INTERVAL: "1000"' in rendered

    def test_dev_watchers_are_dev_profile_only(self) -> None:
        rendered = _render("docker-compose.dev.yml.jinja", _ctx(include_htmx=True))
        watcher_block = rendered.split("build-static-watcher:", 1)[1]
        assert "profiles:" in watcher_block

    def test_prod_compose_has_no_watchers(self) -> None:
        """CSS is baked into the image at build time; a prod watcher would
        be rebuilding assets on a production host."""
        rendered = _render("docker-compose.prod.yml.jinja", _ctx(include_htmx=True))
        assert "tailwind" not in rendered
        assert "build-static-watcher" not in rendered

    def test_compose_output_unchanged_without_htmx(self) -> None:
        dev = _render("docker-compose.dev.yml.jinja", _ctx())
        assert "tailwind" not in dev
        assert "build-static-watcher" not in dev
        assert "CHOKIDAR" not in dev

    def test_htmx_adds_no_host_ports(self) -> None:
        """The htmx frontend rides the existing webserver process and port;
        a new host port would collide with resolve-ports.sh."""
        off = _render("docker-compose.dev.yml.jinja", _ctx())
        on = _render("docker-compose.dev.yml.jinja", _ctx(include_htmx=True))
        assert on.count("ports:") == off.count("ports:")

    def test_added_compose_services_carry_no_inline_comments(self) -> None:
        """Component selection varies per project, so a comment written for
        one stack misleads in another."""
        rendered = _render("docker-compose.dev.yml.jinja", _ctx(include_htmx=True))
        added = rendered.split("  tailwind:", 1)[1]
        for line in added.splitlines():
            assert not line.strip().startswith("#"), line


class TestAuthPages:
    """Auth pages (HF-10) — present only when htmx AND auth are both on."""

    def test_auth_pages_ship(self) -> None:
        root = _web_frontend_tree() / "templates/pages/auth"
        for rel in (
            "_layout.html",
            "login.html",
            "register.html",
            "forgot_password.html",
            "reset_password.html",
            "verify_email.html",
            "verify_pending.html",
        ):
            assert (root / rel).is_file(), rel

    def test_auth_handlers_are_gated_on_the_auth_service(self) -> None:
        off = _render("app/components/web_frontend/routes/pages.py.jinja", _ctx())
        assert "/login" not in off
        assert "api_login" not in off
        assert "auth" not in off.lower()
        # ...but the landing page still works without auth.
        assert 'name="pages/landing.html"' in off

    def test_auth_handlers_appear_with_auth(self) -> None:
        on = _render(
            "app/components/web_frontend/routes/pages.py.jinja",
            _ctx(include_auth=True),
        )
        for route in ("/login", "/register", "/logout", "/verify-pending"):
            assert f'"{route}"' in on, route

    def test_pages_render_valid_python_both_ways(self) -> None:
        for auth in (False, True):
            ast.parse(
                _render(
                    "app/components/web_frontend/routes/pages.py.jinja",
                    _ctx(include_auth=auth),
                )
            )

    def test_login_delegates_rather_than_reimplementing_auth(self) -> None:
        """The API's login owns lockout, audit and token minting. A second
        copy here would silently drift out of step with it."""
        on = _render(
            "app/components/web_frontend/routes/pages.py.jinja",
            _ctx(include_auth=True),
        )
        assert "api_login" in on
        assert "api_register" in on
        # The giveaways of a reimplementation.
        assert "verify_password" not in on
        assert "create_access_token" not in on
        assert "record_failed_login" not in on

    def test_page_login_is_rate_limited_like_the_api(self) -> None:
        """Delegation passes _rate_limit=None, so the page route must declare
        the limiter itself or this path is an unthrottled way in."""
        on = _render(
            "app/components/web_frontend/routes/pages.py.jinja",
            _ctx(include_auth=True),
        )
        assert "Depends(login_rate_limit)" in on
        assert "Depends(register_rate_limit)" in on

    def test_next_is_not_an_open_redirect(self) -> None:
        on = _render(
            "app/components/web_frontend/routes/pages.py.jinja",
            _ctx(include_auth=True),
        )
        assert "_safe_next" in on
        assert 'startswith("//")' in on

    def test_no_default_deny_middleware(self) -> None:
        """Page protection is opt-in via _current_user_or_redirect, matching
        the API's contract. Two mechanisms would be one too many."""
        on = _render(
            "app/components/web_frontend/routes/pages.py.jinja",
            _ctx(include_auth=True),
        )
        assert "_current_user_or_redirect" in on
        assert "Middleware" not in on

    def _form_tag(self, page: str) -> str:
        """The page's <form ...> tag. Anchoring on the element rather than
        the file keeps prose about forms (comments explaining what NOT to
        do) from failing the test."""
        import re

        source = (_web_frontend_tree() / f"templates/pages/auth/{page}").read_text()
        match = re.search(r"<form[^>]*>", source)
        assert match, f"{page} has no form"
        return match.group(0)

    def test_login_uses_a_native_form_post(self) -> None:
        """A fetch()-based submit silently kills the browser's save-password
        prompt; the native POST + redirect is what triggers it."""
        tag = self._form_tag("login.html")
        assert 'action="/login"' in tag
        assert 'method="post"' in tag
        assert "@submit.prevent" not in tag
        login = (_web_frontend_tree() / "templates/pages/auth/login.html").read_text()
        assert 'autocomplete="current-password"' in login

    def test_register_marks_the_password_as_new(self) -> None:
        page = (_web_frontend_tree() / "templates/pages/auth/register.html").read_text()
        assert 'action="/register" method="post"' in page
        assert 'autocomplete="new-password"' in page

    def test_auth_js_refresh_is_single_flight(self) -> None:
        """Parallel 401s must share one refresh: the server rotates refresh
        tokens with reuse detection, so a second concurrent call would replay
        a just-rotated token and revoke the family."""
        source = (_web_frontend_tree() / "static/js/auth.js").read_text()
        assert "_refreshInFlight" in source
        assert source.count("fetch('/api/v1/auth/refresh'") == 1

    def test_auth_js_is_loaded_only_when_auth_is_enabled(self) -> None:
        base = (_web_frontend_tree() / "templates/base.html").read_text()
        assert "{% if auth_enabled %}" in base
        assert "js/auth.js" in base

    def test_auth_layout_hides_token_urls_from_crawlers(self) -> None:
        layout = (
            _web_frontend_tree() / "templates/pages/auth/_layout.html"
        ).read_text()
        assert 'content="noindex, nofollow"' in layout

    def test_auth_files_are_owned_by_the_auth_service(self) -> None:
        """htmx-without-auth must ship no auth pages or JS; the auth spec is
        what removes them.

        Since issue #814 these live in the ``include_htmx`` extras group (so
        the add path only copies them into projects that actually ship the
        htmx frontend), but ownership is unchanged: the cleanup footprint
        (primary + extras) still covers them, so removing auth removes them.
        """
        from aegis.core.component_files import get_component_cleanup_paths
        from aegis.core.services import SERVICES

        htmx_extras = SERVICES["auth"].files.extras["include_htmx"]
        assert "app/components/web_frontend/templates/pages/auth" in htmx_extras
        assert "app/components/web_frontend/static/js/auth.js" in htmx_extras

        cleanup = get_component_cleanup_paths("auth")
        assert "app/components/web_frontend/templates/pages/auth" in cleanup
        assert "app/components/web_frontend/static/js/auth.js" in cleanup

    def test_auth_pages_carry_no_pulse_copy(self) -> None:
        root = _web_frontend_tree() / "templates/pages/auth"
        for page in root.glob("*.html"):
            text = page.read_text().lower()
            assert "pulse" not in text, page.name
            assert "four sources" not in text, page.name


class TestGeneratedWebFrontendTests:
    """The generated project ships its own tests for this code, gated."""

    PATH = "tests/components/test_web_frontend.py.jinja"

    def test_renders_empty_when_htmx_off(self) -> None:
        assert _render(self.PATH, _ctx()).strip() == ""

    def test_renders_valid_python_when_htmx_on(self) -> None:
        ast.parse(_render(self.PATH, _ctx(include_htmx=True)))
