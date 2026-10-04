"""Overseer ships with the web frontend, not with auth: auth adds sign-in
and admins-only when it is there, and without it Overseer is open, its
writes (Restart, Secrets) included."""

from __future__ import annotations

import ast
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path
from aegis.core.services import SERVICES

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"
WEB = "app/components/web_frontend"
# What auth removes from a web frontend without it: its own pages only.
AUTHS_OWN = {
    f"{WEB}/templates/pages/auth",
    f"{WEB}/templates/pages/overseer/auth",
    f"{WEB}/templates/pages/overseer/login.html",
    f"{WEB}/templates/pages/overseer/forbidden.html",
    f"{WEB}/templates/components/auth_macros.html",
    f"{WEB}/static/js/auth.js",
    f"{WEB}/overseer_auth.py",
    f"{WEB}/routes/partials/overseer_auth.py",
    "tests/web/test_login_refusals.py",
    "tests/web/test_auth_js_streams.py",
    "tests/web/test_overseer_auth.py",
    "tests/web/test_overseer_admin_gate.py",
}


def _render(path: str, **answers: Any) -> str:
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())), keep_trailing_newline=True
    )
    context = {**get_copier_defaults(), "project_slug": "demo", **answers}
    return env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/{path}").render(context)


def test_auth_takes_only_its_own_pages_with_it() -> None:
    removed = set(SERVICES["auth"].files.extras["include_htmx"])
    assert removed <= AUTHS_OWN, sorted(removed - AUTHS_OWN)


def test_the_pages_mount_overseer_without_auth() -> None:
    pages = _render(
        f"{WEB}/routes/pages.py.jinja", include_htmx=True, include_auth=False
    )
    ast.parse(pages)
    assert "overseer_routes.router" in pages
    assert "Depends(overseer_gate)" in pages


def test_without_auth_the_gate_lets_everyone_in() -> None:
    access = _render(f"{WEB}/overseer_access.py.jinja", include_auth=False)
    tree = ast.parse(access)
    gate = next(
        n
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "overseer_gate"
    )
    assert not [n for n in ast.walk(gate) if isinstance(n, ast.Raise)]


def test_the_write_apis_mount_without_auth() -> None:
    routing = _render(
        "app/components/backend/api/routing.py.jinja",
        include_deploy=True,
        include_secrets=True,
        include_database=True,
        include_auth=False,
    )
    assert "include_router(deploy_router" in routing
    assert "include_router(secrets_router" in routing
    for router in ("deploy", "secrets"):
        source = (
            get_template_path()
            / PROJECT_SLUG_PLACEHOLDER
            / f"app/components/backend/api/{router}/router.py"
        ).read_text()
        assert "app.services.auth" not in source, router


@pytest.mark.parametrize(
    "answers",
    [
        {"include_secrets": True, "include_database": True},
        {"include_insights": True, "include_database": True},
    ],
)
def test_what_encrypts_brings_its_own_cryptography(answers: dict[str, Any]) -> None:
    """The secrets store and insights encrypt at rest (``app.core.encryption``);
    without auth nothing else installs ``cryptography`` for them."""
    pyproject = _render("pyproject.toml.jinja", include_auth=False, **answers)
    assert '"cryptography>=' in pyproject
