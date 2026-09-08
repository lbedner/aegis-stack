"""Render tests for blog service templates."""

from __future__ import annotations

import ast

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _render_blog_router(context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())),
        trim_blocks=False,
        lstrip_blocks=False,
    )
    template = env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/app/components/backend/api/blog/router.py.jinja"
    )
    return template.render(context)


def test_blog_router_no_auth_leaves_writes_unprotected() -> None:
    context = {
        **get_copier_defaults(),
        "include_blog": True,
        "include_auth": False,
        "include_auth_rbac": False,
    }

    rendered = _render_blog_router(context)

    ast.parse(rendered)
    assert "require_blog_writer" not in rendered
    assert "current_user" not in rendered
    assert '@router.post("/posts"' in rendered


def test_blog_router_basic_auth_requires_active_user() -> None:
    context = {
        **get_copier_defaults(),
        "include_blog": True,
        "include_auth": True,
        "include_auth_rbac": False,
    }

    rendered = _render_blog_router(context)

    ast.parse(rendered)
    assert "from app.services.auth.deps import get_current_active_user" in rendered
    assert "require_blog_writer = get_current_active_user" in rendered
    assert "require_role" not in rendered
    assert "current_user: User = Depends(require_blog_writer)" in rendered


def test_blog_router_rbac_requires_admin_or_moderator() -> None:
    context = {
        **get_copier_defaults(),
        "include_blog": True,
        "include_auth": True,
        "include_auth_rbac": True,
    }

    rendered = _render_blog_router(context)

    ast.parse(rendered)
    assert "from app.services.auth.service import require_role" in rendered
    assert 'require_blog_writer = require_role("admin", "moderator")' in rendered
    assert "get_current_active_user" not in rendered
