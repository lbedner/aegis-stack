"""Render tests for the generated-project CLAUDE.md template.

Assert the shipped CLAUDE.md is selection-accurate: component/service sections
appear only when selected, the worker section names the chosen backend, and the
file carries no emojis, em-dashes, or internal codenames.
"""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"

# Characters and tokens the shipped file must never contain.
_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x1F1E6, 0x1F1FF),
)
_BANNED_CODENAMES = ("pulse", "overseer", "aegis-stack#", "SK-")


def _render_claude_md(context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())),
        trim_blocks=False,
        lstrip_blocks=False,
    )
    template = env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/CLAUDE.md.jinja")
    return template.render(context)


def _ctx(**overrides: object) -> dict:
    return {
        **get_copier_defaults(),
        "project_name": "Acme App",
        "project_slug": "acme_app",
        **overrides,
    }


def test_base_stack_has_core_content_and_no_optional_sections() -> None:
    rendered = _render_claude_md(_ctx())

    # Identity and always-on guidance.
    assert "Acme App" in rendered
    assert "Aegis Stack" in rendered
    assert "app/components/" in rendered
    assert "app/services/" in rendered
    assert "make check" in rendered
    assert ".env.ports" in rendered
    # CLI law.
    assert "aegis add" in rendered
    assert "aegis update" in rendered
    # Skills pointer (populated by the conditional-skills work).
    assert ".claude/skills/" in rendered

    # No optional sections when nothing optional is selected.
    assert "## Database" not in rendered
    assert "## Worker" not in rendered
    assert "## Scheduler" not in rendered
    assert "## Authentication" not in rendered


def test_database_section_present_iff_selected() -> None:
    without = _render_claude_md(_ctx(include_database=False))
    assert "## Database" not in without

    with_db = _render_claude_md(_ctx(include_database=True))
    assert "## Database" in with_db
    assert "alembic" in with_db.lower()


def test_worker_section_names_chosen_backend() -> None:
    for backend in ("arq", "dramatiq", "taskiq"):
        rendered = _render_claude_md(
            _ctx(include_worker=True, include_redis=True, worker_backend=backend)
        )
        assert "## Worker" in rendered
        assert backend in rendered

    off = _render_claude_md(_ctx(include_worker=False))
    assert "## Worker" not in off


def test_auth_and_scheduler_sections_gate_on_selection() -> None:
    both = _render_claude_md(_ctx(include_auth=True, include_scheduler=True))
    assert "## Authentication" in both
    assert "## Scheduler" in both

    neither = _render_claude_md(_ctx(include_auth=False, include_scheduler=False))
    assert "## Authentication" not in neither
    assert "## Scheduler" not in neither


def test_no_emojis_codenames_or_em_dashes() -> None:
    # An "everything" style stack exercises every conditional block.
    rendered = _render_claude_md(
        _ctx(
            include_database=True,
            include_worker=True,
            include_redis=True,
            include_scheduler=True,
            include_auth=True,
            include_ai=True,
        )
    )

    assert "—" not in rendered, "no em-dashes"
    assert "–" not in rendered, "no en-dashes"
    for ch in rendered:
        cp = ord(ch)
        assert not any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES), (
            f"emoji found: {ch!r}"
        )
    lowered = rendered.lower()
    for token in _BANNED_CODENAMES:
        assert token.lower() not in lowered, f"banned token present: {token}"


def test_evals_section_says_a_regression_ships_with_its_case() -> None:
    assert "## Evals" not in _render_claude_md(_ctx(include_ai=True, ai_evals=False))

    rendered = _render_claude_md(
        _ctx(include_ai=True, ai_evals=True, ai_backend="memory")
    )
    assert "## Evals" in rendered
    assert "evals/" in rendered and "make evals-ci" in rendered
    assert "make evals " not in rendered  # memory keeps no runs: no `make evals`

    kept = _render_claude_md(_ctx(include_ai=True, ai_evals=True, ai_backend="sqlite"))
    assert "`make evals`" in kept
