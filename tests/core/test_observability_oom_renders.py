"""Render-time guards for the OTEL OOM fix.

Issue #627 ships in three artefacts: the logfire middleware (no-token
short-circuit + ``os.environ.setdefault`` for BSP caps), the ``config.py``
settings, the ``.env.example`` overrides, and rightsized memory limits
in ``docker-compose.yml``. These tests fail loudly if any of those
artefacts regresses.
"""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(get_template_path())),
        trim_blocks=False,
        lstrip_blocks=False,
    )


def _render(path: str, context: dict) -> str:
    return _env().get_template(f"{PROJECT_SLUG_PLACEHOLDER}/{path}").render(context)


def _ctx(**overrides) -> dict:
    return {
        **get_copier_defaults(),
        "include_observability": True,
        "include_database": True,
        "include_redis": False,
        "include_worker": False,
        "include_scheduler": False,
        "include_ingress": True,
        **overrides,
    }


def test_logfire_middleware_short_circuits_when_token_unset() -> None:
    rendered = _render(
        "app/components/backend/middleware/logfire_tracing.py.jinja", _ctx()
    )
    assert "if not settings.LOGFIRE_TOKEN" in rendered
    assert "token not set" in rendered
    # Must return before configure() runs.
    assert rendered.index("if not settings.LOGFIRE_TOKEN") < rendered.index(
        "logfire.configure("
    )


def test_logfire_middleware_sets_otel_bsp_env_before_configure() -> None:
    import re

    rendered = _render(
        "app/components/backend/middleware/logfire_tracing.py.jinja", _ctx()
    )
    # Strip whitespace between ``setdefault(`` and the quoted key so
    # the assertion survives ruff formatting that splits the call
    # across lines.
    normalized = re.sub(r"\s+", " ", rendered)
    for key in (
        "OTEL_BSP_MAX_QUEUE_SIZE",
        "OTEL_BSP_MAX_EXPORT_BATCH_SIZE",
        "OTEL_BSP_EXPORT_TIMEOUT",
        "OTEL_BSP_SCHEDULE_DELAY",
    ):
        assert f'os.environ.setdefault( "{key}"' in normalized or (
            f'os.environ.setdefault("{key}"' in normalized
        )
        # Each setdefault must precede the configure call.
        idx = normalized.find(f'"{key}"')
        assert idx >= 0
        assert idx < normalized.index("logfire.configure(")


def test_config_carries_otel_bsp_defaults() -> None:
    rendered = _render("app/core/config.py.jinja", _ctx())
    assert "OTEL_BSP_MAX_QUEUE_SIZE: int = 1024" in rendered
    assert "OTEL_BSP_MAX_EXPORT_BATCH_SIZE: int = 256" in rendered
    assert "OTEL_BSP_EXPORT_TIMEOUT: int = 10000" in rendered
    assert "OTEL_BSP_SCHEDULE_DELAY: int = 5000" in rendered


def test_env_example_documents_otel_bsp_overrides() -> None:
    rendered = _render(".env.example.jinja", _ctx())
    # Commented overrides — operators discover them by reading .env.example.
    assert "# OTEL_BSP_MAX_QUEUE_SIZE=1024" in rendered
    assert "# OTEL_BSP_MAX_EXPORT_BATCH_SIZE=256" in rendered
    assert "# OTEL_BSP_EXPORT_TIMEOUT=10000" in rendered
    assert "# OTEL_BSP_SCHEDULE_DELAY=5000" in rendered


def test_logfire_middleware_omitted_when_observability_off() -> None:
    """When the observability component is off the middleware file is
    never reached — but its config fields shouldn't leak either."""
    ctx = _ctx(include_observability=False)
    rendered = _render("app/core/config.py.jinja", ctx)
    assert "OTEL_BSP_MAX_QUEUE_SIZE" not in rendered


def test_docker_compose_webserver_rightsized_to_768m() -> None:
    rendered = _render("docker-compose.yml.jinja", _ctx())
    # The webserver block is the first ``memory:`` after the
    # ``healthcheck`` for the app service.
    webserver_block = (
        rendered.split("scheduler:")[0]
        if "scheduler:" in rendered
        else rendered.split("# REDIS")[0]
    )
    assert "memory: 768M" in webserver_block
    assert "memory: 512M" not in webserver_block  # old default


def test_docker_compose_drops_app_reservations() -> None:
    """Reservations on the webserver compounded the over-provisioning;
    they are removed in the rightsizing."""
    rendered = _render("docker-compose.yml.jinja", _ctx())
    webserver_block = (
        rendered.split("scheduler:")[0]
        if "scheduler:" in rendered
        else rendered.split("# REDIS")[0]
    )
    # The webserver deploy block should no longer carry a reservation.
    deploy_block = webserver_block.split("deploy:")[-1]
    assert "reservations:" not in deploy_block


def test_docker_compose_redis_rightsized_to_128m() -> None:
    rendered = _render("docker-compose.yml.jinja", _ctx(include_redis=True))
    # ``redis:`` appears as both the service block and the
    # ``redis-server`` command; use the full ``image: redis:`` anchor
    # to find the service block, then walk forward to the next service.
    anchor = "image: redis:7-alpine"
    redis_section = rendered.split(anchor, 1)[1]
    next_service = min(
        (
            redis_section.index(s)
            for s in ("postgres:", "traefik:", "ollama:", "test_runner:")
            if s in redis_section
        ),
        default=len(redis_section),
    )
    assert "memory: 128M" in redis_section[:next_service]


def test_docker_compose_traefik_rightsized_to_128m() -> None:
    rendered = _render("docker-compose.yml.jinja", _ctx(include_ingress=True))
    # Traefik is the last service in the file; everything after its
    # ``image:`` anchor until the file ends is its block.
    anchor = "image: traefik:v3.6"
    traefik_section = rendered.split(anchor, 1)[1]
    assert "memory: 128M" in traefik_section


def test_docker_compose_rightsized_blocks_count_matches() -> None:
    """Whole-file regression guard: with redis + traefik + ingress on,
    exactly two services land at ``memory: 128M`` (redis + traefik) and
    one at ``memory: 768M`` (webserver)."""
    rendered = _render(
        "docker-compose.yml.jinja", _ctx(include_redis=True, include_ingress=True)
    )
    assert rendered.count("memory: 128M") == 2
    assert rendered.count("memory: 768M") == 1


def test_logfire_configure_is_passed_the_settings_token() -> None:
    """The guard reads ``settings.LOGFIRE_TOKEN`` (pydantic-settings, which
    loads ``.env``); ``logfire.configure()`` resolves its own token from
    ``os.environ``, which ``.env`` never populates. Unless the token is
    handed over explicitly those two disagree, the guard passes, and
    ``configure()`` raises ``LogfireConfigError`` (aegis-stack#1135).

    That failure is not confined to observability: the app factory calls
    ``install_auto_tracing()`` at import time, so the application stops
    importing at all outside a container.
    """
    import re

    rendered = _render(
        "app/components/backend/middleware/logfire_tracing.py.jinja", _ctx()
    )
    configure_call = rendered[rendered.index("logfire.configure(") :]
    configure_call = configure_call[: configure_call.index(")")]
    normalized = re.sub(r"\s+", " ", configure_call)
    assert "token=settings.LOGFIRE_TOKEN" in normalized
