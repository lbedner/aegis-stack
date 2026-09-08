"""
Tests for ``aegis.core.plugins.resolver`` (#776).

Forward dependency resolution: given a target plugin, walk its
``required_*`` fields transitively and produce an install plan.
"""

from __future__ import annotations

import pytest

from aegis.core.plugins.resolver import (
    CircularDependencyError,
    ResolutionResult,
    UnknownDependencyError,
    format_plan,
    resolve_dependencies,
)
from aegis.core.plugins.spec import PluginKind, PluginSpec


def _spec(name: str, kind: PluginKind = PluginKind.SERVICE, **kwargs) -> PluginSpec:
    return PluginSpec(name=name, kind=kind, description="", **kwargs)


class TestNoDeps:
    def test_target_with_no_deps_yields_empty_plan(self) -> None:
        target = _spec("standalone")
        result = resolve_dependencies(target, answers={}, registry={})
        assert result.is_empty


class TestComponentDeps:
    def test_missing_component_queued(self) -> None:
        target = _spec("scraper", required_components=["database"])
        registry = {
            "scraper": target,
            "database": _spec("database", kind=PluginKind.COMPONENT),
        }
        # Project doesn't have database installed.
        result = resolve_dependencies(target, answers={}, registry=registry)
        assert [d.name for d in result.to_install] == ["database"]
        assert result.to_install[0].kind == PluginKind.COMPONENT

    def test_already_installed_component_skipped(self) -> None:
        target = _spec("scraper", required_components=["database"])
        registry = {
            "scraper": target,
            "database": _spec("database", kind=PluginKind.COMPONENT),
        }
        result = resolve_dependencies(
            target, answers={"include_database": True}, registry=registry
        )
        assert result.is_empty

    def test_core_components_never_queued(self) -> None:
        """``backend`` / ``frontend`` are CORE_COMPONENTS — always
        present in any aegis project. Listing them as required is
        harmless and the resolver shouldn't queue them."""
        target = _spec("scraper", required_components=["backend"])
        registry = {"scraper": target}
        result = resolve_dependencies(target, answers={}, registry=registry)
        assert result.is_empty


class TestServiceDeps:
    def test_missing_service_queued(self) -> None:
        target = _spec("stripe", required_services=["auth"])
        registry = {
            "stripe": target,
            "auth": _spec("auth"),
        }
        result = resolve_dependencies(target, answers={}, registry=registry)
        assert [d.name for d in result.to_install] == ["auth"]


class TestBracketVariants:
    """A dep like ``auth[org]`` is a request for a service AT a level.
    Presence of the base service is not enough; the resolver compares the
    requested variant against the project's answers and queues an
    upgrade when the project falls short."""

    @staticmethod
    def _auth() -> PluginSpec:
        """The real auth spec: its level option carries the answer key and
        ordering the resolver relies on."""
        from aegis.core.services import SERVICES

        return SERVICES["auth"]

    @classmethod
    def _registry(cls, target: PluginSpec) -> dict[str, PluginSpec]:
        """Target, the real auth spec, and the database component auth
        itself requires; every test marks database installed so only
        auth's own state is under test."""
        return {
            target.name: target,
            "auth": cls._auth(),
            "database": _spec("database", kind=PluginKind.COMPONENT),
        }

    def test_missing_service_is_queued_with_its_variant(self) -> None:
        target = _spec("stripe", required_services=["auth[org]"])
        registry = self._registry(target)
        result = resolve_dependencies(
            target, answers={"include_database": True}, registry=registry
        )
        (dep,) = result.to_install
        assert dep.name == "auth"
        assert dep.variant == "auth[org]"
        assert dep.answers_delta == {"auth_level": "org"}

    def test_missing_service_ignores_stale_default_answers(self) -> None:
        """Answers hold ``auth_level: basic`` from an earlier install or a
        copier default while ``include_auth`` is false. The service is
        absent, so the request is applied, never compared."""
        target = _spec("stripe", required_services=["auth[org]"])
        registry = self._registry(target)
        result = resolve_dependencies(
            target,
            answers={
                "include_database": True,
                "include_auth": False,
                "auth_level": "basic",
            },
            registry=registry,
        )
        (dep,) = result.to_install
        assert dep.answers_delta == {"auth_level": "org"}

    def test_lower_level_installed_is_queued_as_upgrade(self) -> None:
        target = _spec("stripe", required_services=["auth[org]"])
        registry = self._registry(target)
        result = resolve_dependencies(
            target,
            answers={
                "include_database": True,
                "include_auth": True,
                "auth_level": "basic",
            },
            registry=registry,
        )
        (dep,) = result.to_install
        assert dep.name == "auth"
        assert dep.answers_delta == {"auth_level": "org"}

    def test_same_level_installed_is_satisfied(self) -> None:
        target = _spec("stripe", required_services=["auth[org]"])
        registry = self._registry(target)
        result = resolve_dependencies(
            target,
            answers={
                "include_database": True,
                "include_auth": True,
                "auth_level": "org",
            },
            registry=registry,
        )
        assert result.is_empty

    def test_base_name_dep_on_installed_service_is_satisfied(self) -> None:
        """No brackets means any level will do."""
        target = _spec("stripe", required_services=["auth"])
        registry = self._registry(target)
        result = resolve_dependencies(
            target,
            answers={
                "include_database": True,
                "include_auth": True,
                "auth_level": "basic",
            },
            registry=registry,
        )
        assert result.is_empty

    def test_bracket_variant_already_installed_component_skipped(self) -> None:
        """A component with no declared options still collapses to
        presence: ``database[sqlite]`` against ``include_database: true``
        must not re-queue."""
        target = _spec("stripe", required_components=["database[sqlite]"])
        registry = {
            "stripe": target,
            "database": _spec("database", kind=PluginKind.COMPONENT),
        }
        result = resolve_dependencies(
            target, answers={"include_database": True}, registry=registry
        )
        assert result.is_empty


class TestTransitive:
    def test_deepest_first_ordering(self) -> None:
        """``stripe → auth → database`` should install ``database``
        first, then ``auth``, then leave the caller to install ``stripe``.
        Topological order means deps before dependents."""
        database = _spec("database", kind=PluginKind.COMPONENT)
        auth = _spec("auth", required_components=["database"])
        stripe = _spec("stripe", required_services=["auth"])

        registry = {"database": database, "auth": auth, "stripe": stripe}
        result = resolve_dependencies(stripe, answers={}, registry=registry)
        assert [d.name for d in result.to_install] == ["database", "auth"]


class TestPluginDeps:
    def test_unresolved_plugin_dep(self) -> None:
        """Plugin dep that isn't pip-installed (not in registry) lands
        in ``unresolved_plugins`` rather than ``to_install``."""
        target = _spec("dashboard", required_plugins=["base"])
        registry = {"dashboard": target}  # base not registered
        result = resolve_dependencies(target, answers={}, registry=registry)
        assert result.unresolved_plugins == ["base"]
        assert not result.to_install

    def test_resolved_plugin_dep_queued(self) -> None:
        base = _spec("base")
        target = _spec("dashboard", required_plugins=["base"])
        registry = {"dashboard": target, "base": base}
        # Plugin not yet in project's _plugins.
        result = resolve_dependencies(target, answers={}, registry=registry)
        assert [d.name for d in result.to_install] == ["base"]

    def test_already_installed_plugin_skipped(self) -> None:
        base = _spec("base")
        target = _spec("dashboard", required_plugins=["base"])
        registry = {"dashboard": target, "base": base}
        answers = {"_plugins": [{"name": "base"}]}
        result = resolve_dependencies(target, answers=answers, registry=registry)
        assert result.is_empty

    def test_constraint_versions_stripped(self) -> None:
        """``required_plugins=["base>=1.0"]`` resolves to ``"base"``
        in the registry — the version constraint is currently
        informational only, not enforced (#777 handles aegis-version
        constraints, not plugin-to-plugin)."""
        base = _spec("base")
        target = _spec("dashboard", required_plugins=["base>=1.0"])
        registry = {"dashboard": target, "base": base}
        result = resolve_dependencies(target, answers={}, registry=registry)
        assert [d.name for d in result.to_install] == ["base"]


class TestCycles:
    def test_direct_cycle_detected(self) -> None:
        a = _spec("a", required_plugins=["b"])
        b = _spec("b", required_plugins=["a"])
        registry = {"a": a, "b": b}
        with pytest.raises(CircularDependencyError) as exc:
            resolve_dependencies(a, answers={}, registry=registry)
        assert "a" in exc.value.cycle and "b" in exc.value.cycle

    def test_indirect_cycle_detected(self) -> None:
        a = _spec("a", required_plugins=["b"])
        b = _spec("b", required_plugins=["c"])
        c = _spec("c", required_plugins=["a"])
        registry = {"a": a, "b": b, "c": c}
        with pytest.raises(CircularDependencyError):
            resolve_dependencies(a, answers={}, registry=registry)


class TestFormatPlan:
    def test_empty_plan_is_empty_string(self) -> None:
        assert format_plan(ResolutionResult(), "scraper") == ""

    def test_grouped_by_kind(self) -> None:
        target = _spec("stripe", required_services=["auth"])
        registry = {
            "stripe": target,
            "auth": _spec("auth"),
        }
        plan = resolve_dependencies(target, answers={}, registry=registry)
        rendered = format_plan(plan, "stripe")
        assert "stripe" in rendered
        assert "auth" in rendered

    def test_components_render_before_services(self) -> None:
        """``Components: ...`` line must appear before ``Services: ...``
        in the rendered plan, regardless of the topological order in
        which deps were appended to ``to_install``. Stable ordering
        keeps the CLI output deterministic across runs."""
        # ``stripe`` requires ``auth`` (service) which requires
        # ``database`` (component). Topological order pushes database
        # into ``to_install`` first, so dict-iteration ordering would
        # have rendered ``Components`` before ``Services`` — but a
        # different dep tree could flip that. The explicit ordering in
        # ``format_plan`` guarantees it.
        database = _spec("database", kind=PluginKind.COMPONENT)
        auth = _spec("auth", required_components=["database"])
        stripe = _spec("stripe", required_services=["auth"])
        registry = {"database": database, "auth": auth, "stripe": stripe}

        plan = resolve_dependencies(stripe, answers={}, registry=registry)
        rendered = format_plan(plan, "stripe")
        components_idx = rendered.index("Components:")
        services_idx = rendered.index("Services:")
        assert components_idx < services_idx


class TestUnknownDependency:
    def test_unknown_required_service_raises(self) -> None:
        """A typo in ``required_services`` points at a name not in the
        registry. In-tree services are always populated, so the only
        way to hit this is a bad spec — fail loud."""
        target = _spec("stripe", required_services=["does_not_exist"])
        registry = {"stripe": target}
        with pytest.raises(UnknownDependencyError) as exc:
            resolve_dependencies(target, answers={}, registry=registry)
        assert "does_not_exist" in str(exc.value)
        assert "service" in str(exc.value)

    def test_unknown_required_component_raises(self) -> None:
        target = _spec("stripe", required_components=["does_not_exist"])
        registry = {"stripe": target}
        with pytest.raises(UnknownDependencyError) as exc:
            resolve_dependencies(target, answers={}, registry=registry)
        assert "does_not_exist" in str(exc.value)
        assert "component" in str(exc.value)

    def test_unknown_required_plugin_records_unresolved(self) -> None:
        """Plugin-kind misses still go to ``unresolved_plugins`` — the
        user can recover by ``pip install``-ing the missing package."""
        target = _spec("dashboard", required_plugins=["not_pip_installed"])
        registry = {"dashboard": target}
        result = resolve_dependencies(target, answers={}, registry=registry)
        assert result.unresolved_plugins == ["not_pip_installed"]
        assert not result.to_install
