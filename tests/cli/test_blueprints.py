"""Blueprints: named preset configurations driving the shared selection engine.

A blueprint only pre-fills answers — it runs the real ``run_project_selection``
engine (headlessly for ``--blueprint --no-interactive``, via the journal in the
guided flow), so its output is exactly what a user answering the same way would
get. These tests assert that equivalence, the gallery wiring, and the promise
that every shipped blueprint resolves to a legal stack.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aegis.blueprints import BLUEPRINTS, get_blueprint
from aegis.blueprints.spec import Blueprint, QKeys, blueprint_selection
from aegis.cli import guided
from aegis.cli.build_plan import resolve_build_plan
from aegis.cli.guided import GuidedSelectionUI, run_guided_selection
from aegis.core.component_utils import extract_base_component_name
from aegis.core.components import COMPONENTS
from aegis.core.services import SERVICES


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestRegistry:
    """The registry is discovered from the blueprints package."""

    def test_finance_blueprint_registered(self) -> None:
        assert "finance" in BLUEPRINTS
        bp = get_blueprint("finance")
        assert bp is not None
        assert bp.slug == "finance"
        assert bp.title
        assert bp.description

    def test_unknown_slug_returns_none(self) -> None:
        assert get_blueprint("does-not-exist") is None

    def test_slug_matches_module_key(self) -> None:
        # Discovery keys by the blueprint's own slug, so a mismatched
        # module name can never shadow another entry.
        for slug, bp in BLUEPRINTS.items():
            assert slug == bp.slug


class TestAnswerKeys:
    """A blueprint's answers are checked against the real question keys.

    Unknown keys used to fall back to the screen default in silence, so a
    typo shipped a blueprint that quietly built the wrong stack.
    """

    @pytest.mark.parametrize("slug", sorted(BLUEPRINTS))
    def test_blueprints_only_use_known_keys(self, slug: str) -> None:
        unknown = set(BLUEPRINTS[slug].answers) - set(QKeys.ALL)
        assert not unknown, f"{slug} declares unknown answer keys: {unknown}"

    def test_screens_and_constants_stay_in_step(self) -> None:
        # Both directions: no screen asks under a raw string a blueprint
        # could never target, and no constant is declared for a question
        # that no screen actually asks.
        source = Path(inspect.getfile(guided)).read_text()
        assert not re.search(r'qkey="[a-z_]+"', source), (
            "guided screens must pass QKeys constants, not raw strings"
        )
        asked = {
            getattr(QKeys, name) for name in re.findall(r"QKeys\.([A-Z_]+)", source)
        } - {QKeys.ALL}
        assert asked == set(QKeys.ALL)

    def test_unknown_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown answer key"):
            Blueprint(
                slug="bad",
                title="Bad",
                description="Typo'd key.",
                components=(),
                services=(),
                answers={"ai_provider": ("ollama",)},
            )


def _ai_options(state: object) -> set[str]:
    """The bracket options of the resolved ai service, if any."""
    for svc in getattr(state, "services", []):
        if svc.split("[", 1)[0] == "ai" and "[" in svc:
            return set(svc.split("[", 1)[1].rstrip("]").split(","))
    return set()


# Declared answer -> how to see it in the resolved selection. Only keys with
# an unambiguous mapping; the rest are covered by the per-blueprint tests.
_HONORED = {
    QKeys.SCHEDULER_BACKEND: lambda st, v: st.scheduler_backend == v,
    QKeys.DATABASE_ENGINE: lambda st, v: st.database_engine == v,
    QKeys.AI_FRAMEWORK: lambda st, v: v in _ai_options(st),
    QKeys.AI_STORAGE: lambda st, v: v in _ai_options(st),
    QKeys.AI_PROVIDERS: lambda st, v: set(v) <= _ai_options(st),
    QKeys.AUTH_LEVEL: lambda st, v: any(s.startswith(f"auth[{v}") for s in st.services),
}


class TestDeclaredAnswersAreHonored:
    """An answer that silently no-ops is the failure this guards.

    A key can be spelled right, reach its screen, and still not survive
    resolution; nothing else in the suite would notice.
    """

    @pytest.mark.parametrize("slug", sorted(BLUEPRINTS))
    def test_answers_survive_resolution(self, slug: str) -> None:
        bp = BLUEPRINTS[slug]
        state = blueprint_selection(bp)
        for key, value in bp.answers.items():
            check = _HONORED.get(key)
            if check is None or not value:
                continue
            assert check(state, value), (
                f"{slug}: {key}={value!r} did not survive into {state}"
            )


class TestEveryBlueprintIsLegal:
    """Guards against a typo'd component or service shipping in a preset."""

    @pytest.mark.parametrize("slug", sorted(BLUEPRINTS))
    def test_names_exist_in_the_registries(self, slug: str) -> None:
        bp = BLUEPRINTS[slug]
        for name in bp.components:
            assert extract_base_component_name(name) in COMPONENTS, name
        for name in bp.services:
            assert name.split("[", 1)[0] in SERVICES, name

    @pytest.mark.parametrize("slug", sorted(BLUEPRINTS))
    def test_resolves_to_a_build_plan(self, slug: str) -> None:
        bp = BLUEPRINTS[slug]
        state = blueprint_selection(bp)
        plan = resolve_build_plan(
            "bp-check",
            state.components,
            state.scheduler_backend,
            state.services,
            "3.13",
        )
        assert plan.template_gen is not None
        # Every declared component survives resolution (bracket variants and
        # engine auto-adds included).
        resolved = {extract_base_component_name(c) for c in plan.components}
        for name in bp.components:
            assert extract_base_component_name(name) in resolved


class TestHeadlessSelection:
    """``blueprint_selection`` runs the engine with blueprint answers."""

    def test_finance_components(self) -> None:
        state = blueprint_selection(BLUEPRINTS["finance"])
        assert "worker" in state.components
        # Worker acceptance bundles redis via the engine rules.
        assert "redis" in state.components
        assert "scheduler[sqlite]" in state.components
        assert "database[sqlite]" in state.components

    def test_finance_services(self) -> None:
        state = blueprint_selection(BLUEPRINTS["finance"])
        assert state.services == ["ai[sqlite,pydantic-ai,ollama]", "finance"]

    def test_finance_backends(self) -> None:
        state = blueprint_selection(BLUEPRINTS["finance"])
        assert state.scheduler_backend == "sqlite"
        assert state.database_engine == "sqlite"


class TestGuidedSeeding:
    """A blueprint answers EVERY screen silently (journaled like
    keypresses), so the pass lands straight on REVIEW; customization is
    esc-back from there, with the blueprint re-answering on the way
    forward again."""

    def test_seeded_pass_leaves_a_trail(self) -> None:
        # The seeded answers are journaled like real ones, which is what
        # makes the sidebar, esc, and replay work at all.
        ui = GuidedSelectionUI(keys=iter(()))
        ui.set_blueprint(BLUEPRINTS["finance"])
        run_guided_selection(ui)
        assert ui.breadcrumbs

    def test_reset_clears_the_journal_and_the_blueprint(self) -> None:
        # What esc on a blueprint review uses to start over: the trail and
        # the preset both go, so the next pass renders live from scratch.
        ui = GuidedSelectionUI(keys=iter(()))
        ui.set_blueprint(BLUEPRINTS["finance"])
        run_guided_selection(ui)
        assert ui.breadcrumbs
        ui.reset_selection()
        assert ui.breadcrumbs == []
        assert ui.pop_answer() is False


class TestEscFromBlueprintReview:
    """A blueprint user's only decision was the blueprint, so esc undoes
    that: back to the starting point, not into the question journal."""

    def test_esc_returns_to_the_starting_point(self) -> None:
        from aegis.cli.guided import run_guided_init_flow

        # Gallery door, open, pick finance, esc on review -> back at the
        # doors (cursor on blank canvas), take it, decline all 14, build.
        keys = ["down", "\r", "\r", "esc", "\r"] + ["n"] * 15 + ["\r"]
        ui = GuidedSelectionUI(keys=keys)
        plan, _ = run_guided_init_flow("demo", "3.13", ui=ui)
        # Nothing from the blueprint survived: it was un-picked, not edited.
        assert plan.services == []
        assert not [c for c in plan.components if c.startswith("scheduler")]

    def test_esc_can_pick_a_different_blueprint(self) -> None:
        from aegis.cli.guided import run_guided_init_flow

        # esc on review, then back through the gallery to the same preset:
        # the second pass re-seeds cleanly rather than compounding.
        keys = ["down", "\r", "\r", "esc", "down", "\r", "\r", "\r"]
        ui = GuidedSelectionUI(keys=keys)
        plan, _ = run_guided_init_flow("demo", "3.13", ui=ui)
        assert plan.services == ["ai[sqlite,pydantic-ai,ollama]", "finance"]


class TestReviewSidebar:
    """The blueprint review is a clean confirmation, not a selections trail."""

    def _sidebar_flags(self, blueprint: Blueprint | None) -> list[bool]:
        # Capture what show_review passes to _frame across its repaints.
        seen: list[bool] = []
        ui = GuidedSelectionUI(keys=["\r"])
        if blueprint is not None:
            ui.set_blueprint(blueprint)
        real_frame = ui._frame

        def spy(body, hints, *, sidebar: bool = True):  # type: ignore[no-untyped-def]
            seen.append(sidebar)
            return real_frame(body, hints, sidebar=sidebar)

        ui._frame = spy  # type: ignore[method-assign]
        plan = resolve_build_plan("demo", [], "memory", [], "3.13")
        assert ui.show_review(plan) == "build"
        return seen

    def test_blueprint_review_hides_the_sidebar(self) -> None:
        assert self._sidebar_flags(BLUEPRINTS["finance"]) == [False]

    def test_blank_canvas_review_keeps_the_sidebar(self) -> None:
        assert self._sidebar_flags(None) == [True]


class TestCoreStackPage:
    """The foundation page is orientation for someone assembling a stack;
    a blueprint user is not assembling one."""

    def _core_stack_calls(self, keys: list[str], blueprint: Blueprint | None) -> int:
        from aegis.cli.guided import run_guided_init_flow

        ui = GuidedSelectionUI(keys=keys)
        calls = 0

        def spy() -> None:
            nonlocal calls
            calls += 1

        ui.show_core_stack = spy  # type: ignore[method-assign]
        run_guided_init_flow("demo", "3.13", ui=ui, blueprint=blueprint)
        return calls

    def test_blueprint_skips_it(self) -> None:
        # One key: the review confirm. Nothing else renders.
        assert self._core_stack_calls(["\r"], BLUEPRINTS["finance"]) == 0

    def test_blank_canvas_still_shows_it(self) -> None:
        # Blank-canvas door, decline every question, confirm the review.
        # The count is derived: a new component or service adds a screen,
        # and a literal would fail here with a number for a message.
        from aegis.constants import ComponentNames
        from aegis.core.services import SERVICES

        screens = len(ComponentNames.INFRASTRUCTURE_ORDER) + len(SERVICES)
        keys = ["\r"] + ["n"] * screens + ["\r"]
        assert self._core_stack_calls(keys, None) == 1


class TestBuildingScreen:
    """A blueprint build has no trail worth showing; a hand-picked one does."""

    def _sidebar_flags(self, blueprint: Blueprint | None) -> list[bool]:
        seen: list[bool] = []
        ui = GuidedSelectionUI(keys=iter(()))
        if blueprint is not None:
            ui.set_blueprint(blueprint)
        real_frame = ui._frame

        def spy(body, hints, *, sidebar: bool = True):  # type: ignore[no-untyped-def]
            seen.append(sidebar)
            return real_frame(body, hints, sidebar=sidebar)

        ui._frame = spy  # type: ignore[method-assign]
        plan = resolve_build_plan("demo", [], "memory", [], "3.13")
        ui.show_building(plan)
        reporter = ui.build_reporter(plan)
        reporter.step("render", "Rendering project files")
        reporter.done("render")
        assert seen  # the screen painted
        return seen

    def test_blueprint_build_hides_the_sidebar(self) -> None:
        assert not any(self._sidebar_flags(BLUEPRINTS["finance"]))

    def test_blank_canvas_build_keeps_the_sidebar(self) -> None:
        assert all(self._sidebar_flags(None))


class TestDoneScreen:
    """The ready card follows the same rule as review and building."""

    def _sidebar_flags(self, blueprint: Blueprint | None) -> list[bool]:
        seen: list[bool] = []
        ui = GuidedSelectionUI(keys=["\r"])
        if blueprint is not None:
            ui.set_blueprint(blueprint)
        real_frame = ui._frame

        def spy(body, hints, *, sidebar: bool = True):  # type: ignore[no-untyped-def]
            seen.append(sidebar)
            return real_frame(body, hints, sidebar=sidebar)

        ui._frame = spy  # type: ignore[method-assign]
        plan = resolve_build_plan("demo", [], "memory", [], "3.13")
        ui.show_done(plan, "/tmp/demo", "uvx aegis-stack init demo", project_map="")
        assert seen  # the card painted
        return seen

    def test_blueprint_done_hides_the_sidebar(self) -> None:
        assert not any(self._sidebar_flags(BLUEPRINTS["finance"]))

    def test_blank_canvas_done_keeps_the_sidebar(self) -> None:
        assert all(self._sidebar_flags(None))


class TestGallery:
    """Two doors, then the blueprint list."""

    def test_enter_selects_blank_canvas(self) -> None:
        ui = GuidedSelectionUI(keys=["\r"])
        assert ui.choose_blueprint() is None

    def test_second_door_opens_the_gallery(self) -> None:
        # down = "Start from a blueprint", enter opens the gallery, enter
        # picks the focused (first) blueprint.
        ui = GuidedSelectionUI(keys=["down", "\r", "\r"])
        bp = ui.choose_blueprint()
        assert bp is not None
        assert bp.slug in BLUEPRINTS

    def test_esc_in_gallery_returns_to_the_doors(self) -> None:
        # Open the gallery, esc back to the doors (the blueprint door still
        # focused, so `up` is needed), then take blank canvas.
        ui = GuidedSelectionUI(keys=["down", "\r", "esc", "up", "\r"])
        assert ui.choose_blueprint() is None

    def test_gallery_rows_show_contents(self) -> None:
        from rich.console import Console

        ui = GuidedSelectionUI(keys=iter(()))
        console = Console(width=78, record=True)
        console.print(ui._gallery_body(list(BLUEPRINTS.values()), 0, 24))
        out = console.export_text()
        assert "Personal finance" in out
        # Contents are surfaced without selecting the row.
        assert "Finance" in out and "Scheduler" in out

    def test_gallery_scrolls_when_taller_than_the_terminal(self) -> None:
        # A synthetic roster larger than the window still renders and keeps
        # the focused row visible.
        from rich.console import Console

        many = [
            Blueprint(
                slug=f"bp{i}",
                title=f"Blueprint {i}",
                description="A preset.",
                components=(),
                services=(),
            )
            for i in range(30)
        ]
        ui = GuidedSelectionUI(keys=iter(()))
        console = Console(width=78, record=True)
        console.print(ui._gallery_body(many, 29, 24))
        out = console.export_text()
        assert "Blueprint 29" in out
        assert "Blueprint 0\n" not in out  # scrolled out of the window


class TestBlueprintsCommand:
    """``aegis blueprints`` lists the roster for --blueprint discovery."""

    def test_lists_slug_title_and_contents(self, runner: CliRunner) -> None:
        import typer as _typer

        from aegis.commands.blueprints import blueprints_command

        app = _typer.Typer()
        app.command()(blueprints_command)
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "finance" in result.output
        assert "Personal finance" in result.output
        # The usage hint teaches the flag.
        assert "--blueprint" in result.output

    def test_registered_on_the_root_app(self, runner: CliRunner) -> None:
        from aegis.__main__ import app

        result = runner.invoke(app, ["blueprints"])
        assert result.exit_code == 0
        assert "finance" in result.output


class TestBlueprintFlag:
    def test_unknown_slug_errors_before_generation(
        self, runner: CliRunner, tmp_path
    ) -> None:
        from aegis.__main__ import app

        result = runner.invoke(
            app,
            ["init", "bp-test", "--blueprint", "nope", "-o", str(tmp_path), "-y"],
        )
        assert result.exit_code == 1
        assert "nope" in result.output
        assert "finance" in result.output  # available slugs listed

    def test_interactive_flag_routes_to_the_guided_review(self) -> None:
        # --blueprint with the default interactive mode opens the guided
        # experience already seeded (no starting-point screen: the slug IS
        # the choice), landing on REVIEW where one enter builds.
        from aegis.cli.guided import run_guided_init_flow

        ui = GuidedSelectionUI(keys=["\r"])
        plan, _ = run_guided_init_flow(
            "demo", "3.13", ui=ui, blueprint=BLUEPRINTS["finance"]
        )
        service_bases = {s.split("[", 1)[0] for s in plan.services}
        assert {"ai", "finance"} <= service_bases


class TestFullFlow:
    def test_gallery_pick_to_reviewed_plan(self) -> None:
        # Second door, gallery, pick finance, then ONE enter on REVIEW:
        # the blueprint answered everything silently in between.
        from aegis.cli.guided import run_guided_init_flow

        ui = GuidedSelectionUI(keys=["down", "\r", "\r", "\r"])
        plan, _ = run_guided_init_flow("demo", "3.13", ui=ui)
        component_bases = {c.split("[", 1)[0] for c in plan.components}
        service_bases = {s.split("[", 1)[0] for s in plan.services}
        assert {"worker", "redis", "scheduler", "database"} <= component_bases
        assert {"ai", "finance"} <= service_bases
