"""
Tests for the unified PluginSpec contract (R2 of plugin refactor).

These tests lock in:
  * the dataclass shape (required vs default fields, sensible defaults)
  * back-compat aliases (ServiceSpec / ComponentSpec subclass behaviour,
    requires / recommends read-only properties)
  * registry-shape guarantees (every in-tree spec is a PluginSpec with
    a sane kind and verified=True).
"""

import pytest

from aegis.core.components import COMPONENTS, ComponentSpec, ComponentType
from aegis.core.file_manifest import FileManifest
from aegis.core.plugins.spec import PluginKind, PluginSpec
from aegis.core.services import SERVICES, ServiceSpec, ServiceType


class TestPluginSpec:
    """The unified dataclass itself."""

    def test_minimal_construction(self) -> None:
        spec = PluginSpec(name="x", kind=PluginKind.SERVICE, description="d")
        assert spec.name == "x"
        assert spec.kind is PluginKind.SERVICE
        assert spec.description == "d"
        assert spec.type is None
        assert spec.required_components == []
        assert spec.recommended_components == []
        assert spec.required_services == []
        assert spec.required_plugins == []
        assert spec.conflicts == []
        assert spec.pyproject_deps == []
        assert spec.docker_services == []
        assert spec.template_files == []
        assert isinstance(spec.files, FileManifest)
        assert spec.version == "0.0.0"
        assert spec.verified is True

    def test_kind_is_required(self) -> None:
        with pytest.raises(TypeError):
            PluginSpec(name="x", description="d")  # type: ignore[call-arg]

    def test_independent_default_lists(self) -> None:
        a = PluginSpec(name="a", kind=PluginKind.SERVICE, description="")
        b = PluginSpec(name="b", kind=PluginKind.SERVICE, description="")
        a.required_components.append("redis")
        assert b.required_components == []

    def test_requires_alias_reads_required_components(self) -> None:
        spec = PluginSpec(
            name="x",
            kind=PluginKind.COMPONENT,
            description="d",
            required_components=["redis", "database"],
        )
        assert spec.requires == ["redis", "database"]
        assert spec.requires is spec.required_components  # same list

    def test_recommends_alias_reads_recommended_components(self) -> None:
        spec = PluginSpec(
            name="x",
            kind=PluginKind.COMPONENT,
            description="d",
            recommended_components=["backend"],
        )
        assert spec.recommends == ["backend"]
        assert spec.recommends is spec.recommended_components

    def test_unverified_third_party_default_pattern(self) -> None:
        """A third-party plugin would set ``verified=False`` explicitly."""
        spec = PluginSpec(
            name="aegis-stack-scraper",
            kind=PluginKind.SERVICE,
            description="Web scraping",
            verified=False,
            version="0.1.0",
            required_plugins=["auth>=1.0"],
        )
        assert spec.verified is False
        assert spec.version == "0.1.0"
        assert spec.required_plugins == ["auth>=1.0"]


class TestSubclassAliases:
    """ServiceSpec and ComponentSpec are PluginSpec subclasses with a
    pre-baked ``kind`` default. Pre-R2 call sites rely on this.
    """

    def test_servicespec_defaults_kind_service(self) -> None:
        spec = ServiceSpec(name="x", type=ServiceType.AUTH, description="d")
        assert spec.kind is PluginKind.SERVICE
        assert isinstance(spec, PluginSpec)
        assert isinstance(spec, ServiceSpec)

    def test_componentspec_defaults_kind_component(self) -> None:
        spec = ComponentSpec(
            name="x", type=ComponentType.INFRASTRUCTURE, description="d"
        )
        assert spec.kind is PluginKind.COMPONENT
        assert isinstance(spec, PluginSpec)
        assert isinstance(spec, ComponentSpec)

    def test_servicespec_can_override_kind(self) -> None:
        """Just because — ensures the default is overridable, not pinned."""
        spec = ServiceSpec(
            name="x",
            kind=PluginKind.COMPONENT,
            type=ServiceType.AUTH,
            description="d",
        )
        assert spec.kind is PluginKind.COMPONENT


class TestRegistryShape:
    """In-tree services and components are first-party plugins."""

    def test_every_service_is_first_party(self) -> None:
        for name, spec in SERVICES.items():
            assert isinstance(spec, ServiceSpec), f"{name} not a ServiceSpec"
            assert isinstance(spec, PluginSpec)
            assert spec.kind is PluginKind.SERVICE, name
            assert spec.verified is True, f"{name} should be verified=True"
            assert isinstance(spec.type, ServiceType), f"{name} type wrong"

    def test_every_component_is_first_party(self) -> None:
        for name, spec in COMPONENTS.items():
            assert isinstance(spec, ComponentSpec), f"{name} not a ComponentSpec"
            assert isinstance(spec, PluginSpec)
            assert spec.kind is PluginKind.COMPONENT, name
            assert spec.verified is True, f"{name} should be verified=True"
            assert isinstance(spec.type, ComponentType), f"{name} type wrong"

    def test_no_servicespec_in_components(self) -> None:
        """ComponentSpec instances are NOT ServiceSpec instances (sibling subclasses)."""
        for name, spec in COMPONENTS.items():
            assert not isinstance(spec, ServiceSpec), (
                f"component {name} leaked as ServiceSpec"
            )

    def test_no_componentspec_in_services(self) -> None:
        for name, spec in SERVICES.items():
            assert not isinstance(spec, ComponentSpec), (
                f"service {name} leaked as ComponentSpec"
            )
