"""
Tests for the htmx web frontend component registration.

The htmx web frontend is an ADDITIVE optional component: the Flet frontend
stays core and always present, and enabling htmx serves server-rendered
pages at / alongside Flet Overseer at /dashboard. This module covers the
registry entry, constants, template context threading, and dependency
resolution. Template files and their tests land with HF-03/HF-04.
"""

from aegis.constants import AnswerKeys, ComponentNames
from aegis.core.components import COMPONENTS, ComponentSpec, ComponentType


class TestHtmxComponentRegistry:
    """Test htmx component registration in COMPONENTS dict."""

    def test_htmx_exists_in_registry(self) -> None:
        """Test that htmx component is registered."""
        assert "htmx" in COMPONENTS

    def test_htmx_is_component_spec(self) -> None:
        """Test that htmx is a proper ComponentSpec instance."""
        assert isinstance(COMPONENTS["htmx"], ComponentSpec)

    def test_htmx_name_matches_key(self) -> None:
        """Test that component name matches registry key."""
        spec = COMPONENTS["htmx"]
        assert spec.name == "htmx"

    def test_htmx_type_is_frontend(self) -> None:
        """Test that htmx is typed as an optional FRONTEND component.

        The Flet frontend is the CORE frontend; htmx must NOT be core,
        otherwise it could never be prompted, added, or removed. It is
        not infrastructure either — FRONTEND keeps listings truthful.
        """
        spec = COMPONENTS["htmx"]
        assert spec.type == ComponentType.FRONTEND
        assert spec.type != ComponentType.CORE

    def test_htmx_has_description(self) -> None:
        """Test that htmx has a non-empty description naming the stack."""
        spec = COMPONENTS["htmx"]
        assert spec.description
        assert "htmx" in spec.description

    def test_htmx_marker_path_is_web_frontend(self) -> None:
        """Test the on-disk marker matches the Pulse-parity directory name."""
        spec = COMPONENTS["htmx"]
        assert spec.marker_path == "app/components/web_frontend"


class TestHtmxInConstants:
    """Test htmx constants in aegis.constants."""

    def test_htmx_in_component_names(self) -> None:
        """Test that HTMX is defined in ComponentNames."""
        assert hasattr(ComponentNames, "HTMX")
        assert ComponentNames.HTMX == "htmx"

    def test_htmx_in_infrastructure_order(self) -> None:
        """Test that htmx is offered by the interactive flows."""
        assert ComponentNames.HTMX in ComponentNames.INFRASTRUCTURE_ORDER

    def test_htmx_in_answer_keys(self) -> None:
        """Test that HTMX is defined in AnswerKeys."""
        assert hasattr(AnswerKeys, "HTMX")
        assert AnswerKeys.HTMX == "include_htmx"

    def test_include_key_generates_correct_value(self) -> None:
        """Test that the generic add-path key helper works for htmx."""
        assert AnswerKeys.include_key("htmx") == "include_htmx"


class TestHtmxTemplateContext:
    """Test include_htmx threading through TemplateGenerator."""

    def test_htmx_selected_sets_flag_yes(self) -> None:
        """Selecting the htmx component sets include_htmx to yes."""
        from aegis.core.template_generator import TemplateGenerator

        gen = TemplateGenerator(
            project_name="test-htmx",
            selected_components=["htmx"],
        )
        context = gen.get_template_context()
        assert context[AnswerKeys.HTMX] == "yes"

    def test_htmx_not_selected_sets_flag_no(self) -> None:
        """Without the htmx component the flag defaults to no."""
        from aegis.core.template_generator import TemplateGenerator

        gen = TemplateGenerator(
            project_name="test-plain",
            selected_components=[],
        )
        context = gen.get_template_context()
        assert context[AnswerKeys.HTMX] == "no"

    def test_htmx_does_not_disturb_flet_frontend(self) -> None:
        """The Flet frontend stays in the component set with htmx selected."""
        from aegis.core.template_generator import TemplateGenerator

        gen = TemplateGenerator(
            project_name="test-htmx",
            selected_components=["htmx"],
        )
        assert ComponentNames.FRONTEND in gen.components


class TestHtmxRemainsOptionalEverywhere:
    """FRONTEND-typed components must behave like any optional component.

    Every surface that used to filter on ``type == INFRASTRUCTURE`` really
    means "optional component" — these pin htmx into each one so the
    FRONTEND type can never silently drop it.
    """

    def test_interactive_selection_offers_htmx(self) -> None:
        from aegis.cli.interactive import get_interactive_infrastructure_components

        names = [spec.name for spec in get_interactive_infrastructure_components()]
        assert "htmx" in names

    def test_build_plan_files_htmx_under_frontend_not_infrastructure(self) -> None:
        """htmx is FRONTEND-typed, so every preview reading these lists
        describes it as a frontend rather than as infrastructure."""
        from aegis.cli.build_plan import BuildPlan

        plan = BuildPlan(
            project_name="t",
            components=["backend", "frontend", "worker", "htmx"],
            services=[],
            scheduler_backend="memory",
        )
        assert plan.frontend == ["htmx"]
        assert plan.infrastructure == ["worker"]

    def test_build_plan_lists_exclude_core_and_stay_disjoint(self) -> None:
        from aegis.cli.build_plan import BuildPlan

        plan = BuildPlan(
            project_name="t",
            components=["backend", "frontend", "worker", "htmx"],
            services=[],
            scheduler_backend="memory",
        )
        assert set(plan.frontend).isdisjoint(plan.infrastructure)
        for core in ("backend", "frontend"):
            assert core not in plan.infrastructure
            assert core not in plan.frontend

    def test_components_command_lists_htmx(self, capsys) -> None:
        from aegis.commands.components import components_command

        components_command()
        out = capsys.readouterr().out
        assert "htmx" in out


class TestHtmxIsNotCalledInfrastructure:
    """The two build previews must not describe htmx as infrastructure.

    ``aegis components`` grew a truthful FRONTEND section when the type
    landed; these are the other two places a user reads the same fact.
    """

    def _preview(self, components: list[str], capsys) -> str:
        from aegis.commands.init import _show_config_and_confirm
        from aegis.core.template_generator import TemplateGenerator

        gen = TemplateGenerator(project_name="t", selected_components=components)
        _show_config_and_confirm("t", components, [], gen, yes=True)
        return capsys.readouterr().out

    def _line_with(self, out: str, label: str) -> str:
        return next(line for line in out.splitlines() if label in line)

    def test_quick_preview_files_htmx_under_web_frontend(self, capsys) -> None:
        out = self._preview(["worker", "htmx"], capsys)
        infra = self._line_with(out, "Infrastructure:")
        web = self._line_with(out, "Web frontend:")
        assert "worker" in infra
        assert "htmx" not in infra
        assert "htmx" in web

    def test_quick_preview_omits_web_frontend_line_without_htmx(self, capsys) -> None:
        out = self._preview(["worker"], capsys)
        assert "Web frontend:" not in out

    def test_guided_review_files_htmx_under_web_frontend(self) -> None:
        from rich.console import Console

        from aegis.cli.build_plan import BuildPlan
        from aegis.cli.guided import GuidedSelectionUI

        plan = BuildPlan(
            project_name="t",
            components=["backend", "frontend", "worker", "htmx"],
            services=[],
            scheduler_backend="memory",
        )
        console = Console(width=100, record=True)
        console.print(GuidedSelectionUI(keys=[])._review_body(plan, None))
        out = console.export_text()

        infra = self._line_with(out, "Infrastructure:")
        web = self._line_with(out, "Web frontend:")
        assert "worker" in infra
        assert "htmx" not in infra
        assert "htmx" in web


class TestHtmxDependencyResolution:
    """Test htmx through the dependency resolver."""

    def test_htmx_brings_deploy(self) -> None:
        """Overseer's container stats and logs come through deploy's socket
        proxy, so htmx pulls deploy in."""
        from aegis.core.dependency_resolver import DependencyResolver

        resolver = DependencyResolver()
        resolved = resolver.resolve_dependencies([ComponentNames.HTMX])

        assert set(resolved) == {ComponentNames.HTMX, ComponentNames.DEPLOY}


class TestHtmxI18n:
    """Test htmx component description keys exist in the English catalog."""

    def test_component_htmx_keys_in_english_catalog(self) -> None:
        """Both the short and long description keys must exist.

        Locale parity for the other languages is enforced globally by
        tests/core/test_i18n.py; this pins the English source keys.
        """
        from aegis.i18n.locales.en import MESSAGES

        assert "component.htmx" in MESSAGES
        assert "component.htmx.long" in MESSAGES
