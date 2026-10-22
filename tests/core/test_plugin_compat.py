"""
Tests for ``aegis.core.plugin_compat``.

Round 8 (#771) introduced :func:`reverse_dependents` to support the
reverse-dependency check that ``aegis remove`` runs before letting the
user delete a service or plugin that something else still relies on.

Round 11 (#777) added :func:`check_aegis_version_compat` for the
``aegis_version`` constraint plugins declare.
"""

from __future__ import annotations

from aegis.core.plugins.compat import (
    check_aegis_version_compat,
    reverse_dependents,
)
from aegis.core.plugins.spec import PluginKind, PluginSpec


def _spec(name: str, **kwargs) -> PluginSpec:
    return PluginSpec(
        name=name,
        kind=PluginKind.SERVICE,
        description="",
        **kwargs,
    )


class TestReverseDependents:
    def test_no_dependents_returns_empty(self) -> None:
        candidates = [
            _spec("auth"),
            _spec("ai"),
        ]
        answers = {"include_auth": True, "include_ai": True}
        assert reverse_dependents("auth", candidates, answers) == []

    def test_required_service_dependency_detected(self) -> None:
        """``insights.required_services = ["auth"]`` means insights
        depends on auth — removing auth should flag insights."""
        candidates = [
            _spec("auth"),
            _spec("insights", required_services=["auth"]),
        ]
        answers = {"include_auth": True, "include_insights": True}

        deps = reverse_dependents("auth", candidates, answers)
        assert deps == ["insights"]

    def test_required_plugin_dependency_detected(self) -> None:
        """A plugin's ``required_plugins`` entry blocks removal of a
        plugin it depends on."""
        candidates = [
            _spec("scraper"),
            _spec("dashboard", required_plugins=["scraper"]),
        ]
        # Plugins recorded in ``_plugins`` answer key.
        answers = {
            "_plugins": [{"name": "scraper"}, {"name": "dashboard"}],
        }

        deps = reverse_dependents("scraper", candidates, answers)
        assert deps == ["dashboard"]

    def test_required_component_dependency_detected(self) -> None:
        candidates = [
            _spec("auth", required_components=["database"]),
        ]
        answers = {"include_auth": True, "include_database": True}

        deps = reverse_dependents("database", candidates, answers)
        assert deps == ["auth"]

    def test_uninstalled_dependent_ignored(self) -> None:
        """A spec that *would* depend on the target but isn't installed
        in the project doesn't count — removing the target is safe."""
        candidates = [
            _spec("auth"),
            _spec("insights", required_services=["auth"]),
        ]
        # insights is not installed.
        answers = {"include_auth": True, "include_insights": False}

        assert reverse_dependents("auth", candidates, answers) == []

    def test_self_excluded(self) -> None:
        """A spec doesn't count itself as a reverse-dependent (defensive
        — this would only happen with a malformed self-referential spec,
        but the helper should still handle it)."""
        candidates = [_spec("auth", required_services=["auth"])]
        answers = {"include_auth": True}

        assert reverse_dependents("auth", candidates, answers) == []

    def test_constraint_versions_stripped(self) -> None:
        """``required_plugins=["scraper>=1.0"]`` matches target
        ``"scraper"`` — version constraints don't break the lookup."""
        candidates = [
            _spec("scraper"),
            _spec("dashboard", required_plugins=["scraper>=1.0"]),
        ]
        answers = {"_plugins": [{"name": "scraper"}, {"name": "dashboard"}]}

        deps = reverse_dependents("scraper", candidates, answers)
        assert deps == ["dashboard"]


class TestCheckAegisVersionCompat:
    def test_empty_constraint_is_compatible(self) -> None:
        """Plugins predating #777 declare no constraint — install
        unconditionally, no warnings."""
        spec = _spec("legacy")  # aegis_version="" by default
        compatible, msg = check_aegis_version_compat(
            spec, current_aegis_version="0.6.11"
        )
        assert compatible
        assert msg == ""

    def test_satisfied_constraint_is_compatible(self) -> None:
        spec = _spec("scraper", aegis_version=">=0.6,<0.8")
        compatible, msg = check_aegis_version_compat(
            spec, current_aegis_version="0.7.2"
        )
        assert compatible
        assert msg == ""

    def test_outside_lower_bound_rejected(self) -> None:
        spec = _spec("scraper", aegis_version=">=0.7")
        compatible, msg = check_aegis_version_compat(
            spec, current_aegis_version="0.6.11"
        )
        assert not compatible
        assert "scraper" in msg
        assert ">=0.7" in msg
        assert "0.6.11" in msg

    def test_outside_upper_bound_rejected(self) -> None:
        spec = _spec("scraper", aegis_version="<0.7")
        compatible, msg = check_aegis_version_compat(
            spec, current_aegis_version="0.7.2"
        )
        assert not compatible
        assert "<0.7" in msg

    def test_invalid_specifier_string_rejected(self) -> None:
        spec = _spec("scraper", aegis_version="not a real spec")
        compatible, msg = check_aegis_version_compat(
            spec, current_aegis_version="0.6.11"
        )
        assert not compatible
        assert "invalid aegis_version" in msg

    def test_pre_release_excluded_by_default(self) -> None:
        """``packaging.SpecifierSet`` rejects pre-releases by default,
        matching pip behaviour. The wrapper inherits that — a CLI on
        ``0.7.0rc1`` is treated as outside ``>=0.6,<0.8`` even though
        the stable ``0.7.0`` would satisfy. Plugin authors who want to
        accept pre-releases would have to widen their constraint
        explicitly; we don't second-guess pip here."""
        spec = _spec("scraper", aegis_version=">=0.6,<0.8")
        compatible, msg = check_aegis_version_compat(
            spec, current_aegis_version="0.7.0rc1"
        )
        assert not compatible
        assert "0.7.0rc1" in msg

    def test_pre_release_accepted_when_the_constraint_names_one(self) -> None:
        """A constraint that itself names a pre-release accepts them, as
        pip does: the author asked for it."""
        spec = _spec("scraper", aegis_version=">=0.7.0rc1")
        compatible, _ = check_aegis_version_compat(
            spec, current_aegis_version="0.7.0rc2"
        )
        assert compatible

    def test_stable_in_range_accepted(self) -> None:
        spec = _spec("scraper", aegis_version=">=0.6,<0.8")
        compatible, msg = check_aegis_version_compat(
            spec, current_aegis_version="0.7.0"
        )
        assert compatible
        assert msg == ""
