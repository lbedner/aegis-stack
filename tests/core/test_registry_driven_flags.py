"""The plugin registries drive per-flag bookkeeping, not hand-written lists.

Historically every bool component/service flag was hand-maintained in four
places: copier.yml, .copier-answers.yml.jinja, the TemplateGenerator context
("yes"/"no" strings), and copier_manager's copier_data (yes/no back to bool).
The last two are derivable: every spec already knows its ``include_<name>``
answer key, so the context and copier_data entries must come from looping
COMPONENTS/SERVICES. These tests register a throwaway spec and assert it
flows through with zero extra bookkeeping — if they fail, a hand-written
flag list has crept back in.

copier.yml and .copier-answers.yml.jinja remain hand-maintained (Copier
reads them as static files); the registry-sync tests in
tests/cli/test_shared_files_completeness.py and the htmx suite cover those.
"""

import pytest

from aegis.constants import AnswerKeys
from aegis.core.components import COMPONENTS, ComponentSpec, ComponentType
from aegis.core.copier_manager import derive_include_flags
from aegis.core.services import SERVICES, ServiceSpec
from aegis.core.template_generator import TemplateGenerator

FAKE_COMPONENT = "faketestcomp"
FAKE_SERVICE = "faketestsvc"


@pytest.fixture
def fake_component(monkeypatch: pytest.MonkeyPatch) -> ComponentSpec:
    spec = ComponentSpec(
        name=FAKE_COMPONENT,
        type=ComponentType.INFRASTRUCTURE,
        description="Throwaway component for registry-derivation tests",
    )
    monkeypatch.setitem(COMPONENTS, FAKE_COMPONENT, spec)
    return spec


@pytest.fixture
def fake_service(monkeypatch: pytest.MonkeyPatch) -> ServiceSpec:
    spec = ServiceSpec(
        name=FAKE_SERVICE,
        description="Throwaway service for registry-derivation tests",
    )
    monkeypatch.setitem(SERVICES, FAKE_SERVICE, spec)
    return spec


class TestTemplateContextDerivation:
    """get_template_context() emits one flag per optional spec, from the registry."""

    def test_context_covers_every_optional_component(self) -> None:
        context = TemplateGenerator("t", selected_components=[]).get_template_context()
        for name, spec in COMPONENTS.items():
            if spec.type == ComponentType.CORE:
                continue
            assert context.get(AnswerKeys.include_key(name)) == "no", name

    def test_context_covers_every_service(self) -> None:
        context = TemplateGenerator("t", selected_components=[]).get_template_context()
        for name in SERVICES:
            assert context.get(AnswerKeys.include_key(name)) == "no", name

    def test_new_component_flows_into_context(
        self, fake_component: ComponentSpec
    ) -> None:
        selected = TemplateGenerator(
            "t", selected_components=[FAKE_COMPONENT]
        ).get_template_context()
        assert selected[AnswerKeys.include_key(FAKE_COMPONENT)] == "yes"

        unselected = TemplateGenerator(
            "t", selected_components=[]
        ).get_template_context()
        assert unselected[AnswerKeys.include_key(FAKE_COMPONENT)] == "no"

    def test_new_service_flows_into_context(self, fake_service: ServiceSpec) -> None:
        selected = TemplateGenerator(
            "t", selected_components=[], selected_services=[FAKE_SERVICE]
        ).get_template_context()
        assert selected[AnswerKeys.include_key(FAKE_SERVICE)] == "yes"

        unselected = TemplateGenerator(
            "t", selected_components=[]
        ).get_template_context()
        assert unselected[AnswerKeys.include_key(FAKE_SERVICE)] == "no"

    def test_bracket_syntax_still_sets_component_flag(self) -> None:
        context = TemplateGenerator(
            "t", selected_components=["worker[dramatiq]", "scheduler[sqlite]"]
        ).get_template_context()
        assert context[AnswerKeys.WORKER] == "yes"
        assert context[AnswerKeys.SCHEDULER] == "yes"

    def test_bracket_syntax_still_sets_service_flag(self) -> None:
        context = TemplateGenerator(
            "t", selected_components=[], selected_services=["auth[rbac]"]
        ).get_template_context()
        assert context[AnswerKeys.AUTH] == "yes"


class TestCopierDataDerivation:
    """derive_include_flags() converts every registry flag to a Copier bool."""

    def test_flags_convert_yes_no_to_bool(self) -> None:
        context = TemplateGenerator(
            "t", selected_components=["redis"]
        ).get_template_context()
        flags = derive_include_flags(context)
        assert flags[AnswerKeys.REDIS] is True
        assert flags[AnswerKeys.DATABASE] is False
        assert flags[AnswerKeys.AUTH] is False

    def test_covers_every_optional_spec(self) -> None:
        context = TemplateGenerator("t", selected_components=[]).get_template_context()
        flags = derive_include_flags(context)
        for name, spec in COMPONENTS.items():
            if spec.type == ComponentType.CORE:
                continue
            assert flags.get(AnswerKeys.include_key(name)) is False, name
        for name in SERVICES:
            assert flags.get(AnswerKeys.include_key(name)) is False, name

    def test_missing_context_key_defaults_false(self) -> None:
        flags = derive_include_flags({})
        assert all(value is False for value in flags.values())
        assert AnswerKeys.WORKER in flags

    def test_new_spec_flows_into_copier_flags(
        self, fake_component: ComponentSpec, fake_service: ServiceSpec
    ) -> None:
        context = TemplateGenerator(
            "t",
            selected_components=[FAKE_COMPONENT],
            selected_services=[FAKE_SERVICE],
        ).get_template_context()
        flags = derive_include_flags(context)
        assert flags[AnswerKeys.include_key(FAKE_COMPONENT)] is True
        assert flags[AnswerKeys.include_key(FAKE_SERVICE)] is True

    def test_core_components_get_no_flag(self) -> None:
        flags = derive_include_flags({})
        assert "include_backend" not in flags
        assert "include_frontend" not in flags
