"""
Tests for service dependency resolution.

Tests the ServiceResolver class and service-to-component dependency logic.
"""

from unittest import mock

import pytest

from aegis.core.service_resolver import ServiceResolver
from aegis.core.services import SERVICES, ServiceSpec


class TestServiceResolver:
    """Test core service resolver functionality."""

    def test_resolve_service_dependencies_auth(self):
        """Test resolving auth service dependencies."""
        services = ["auth"]

        resolved_components, auto_added = ServiceResolver.resolve_service_dependencies(
            services
        )

        # Auth requires backend and database (no automatic frontend inclusion)
        assert "backend" in resolved_components
        assert "database" in resolved_components

        # Auto-added should include backend and database (required by auth)
        assert "backend" in auto_added
        assert "database" in auto_added

    def test_resolve_service_dependencies_empty(self):
        """Test resolving empty service list."""
        services = []

        resolved_components, auto_added = ServiceResolver.resolve_service_dependencies(
            services
        )

        assert resolved_components == []
        assert auto_added == []

    def test_resolve_service_dependencies_unknown_service(self):
        """Test resolving unknown service raises error."""
        services = ["unknown_service"]

        with pytest.raises(ValueError, match="Invalid services"):
            ServiceResolver.resolve_service_dependencies(services)

    def test_validate_services_success(self):
        """Test successful service validation."""
        services = ["auth"]

        errors = ServiceResolver.validate_services(services)

        assert errors == []

    def test_validate_services_unknown(self):
        """Test validation of unknown services."""
        services = ["unknown_service"]

        errors = ServiceResolver.validate_services(services)

        assert len(errors) == 1
        assert "Unknown service: unknown_service" in errors[0]

    def test_validate_services_conflicts(self):
        """Test validation of service conflicts."""

        # Create a test service that conflicts with auth
        test_service = ServiceSpec(
            name="conflicting_auth",
            description="Conflicting auth service",
            conflicts=["auth"],
        )

        # Mock the SERVICES dict to include the conflicting service
        test_services = SERVICES.copy()
        test_services["conflicting_auth"] = test_service

        with mock.patch.dict(
            "aegis.core.service_resolver.SERVICES", test_services, clear=False
        ):
            errors = ServiceResolver.validate_services(["auth", "conflicting_auth"])

            assert len(errors) >= 1
            conflict_errors = [e for e in errors if "conflicts with" in e]
            assert len(conflict_errors) > 0

    def test_validate_services_required_services(self):
        """Test validation of service-to-service dependencies."""
        # Create a test service that requires auth
        test_service = ServiceSpec(
            name="profile_service",
            description="User profile service",
            required_services=["auth"],
        )

        # Mock the SERVICES dict to include the dependent service
        test_services = SERVICES.copy()
        test_services["profile_service"] = test_service

        with mock.patch.dict(
            "aegis.core.service_resolver.SERVICES", test_services, clear=False
        ):
            # Should fail when profile_service is selected without auth
            errors = ServiceResolver.validate_services(["profile_service"])

            assert len(errors) >= 1
            dependency_errors = [e for e in errors if "requires service" in e]
            assert len(dependency_errors) > 0

            # Should pass when both are selected
            errors = ServiceResolver.validate_services(["auth", "profile_service"])
            assert errors == []

    def test_get_missing_components_for_services(self):
        """Test getting missing components for services."""
        services = ["auth"]
        available_components = ["backend"]  # Missing database

        missing = ServiceResolver.get_missing_components_for_services(
            services, available_components
        )

        assert "database" in missing
        assert "backend" not in missing  # Already available

    def test_get_missing_components_for_services_empty(self):
        """Test getting missing components for empty service list."""
        missing = ServiceResolver.get_missing_components_for_services([], ["backend"])

        assert missing == []

    def test_get_missing_components_for_services_invalid(self):
        """Test getting missing components for invalid services."""
        services = ["unknown_service"]
        available_components = ["backend"]

        missing = ServiceResolver.get_missing_components_for_services(
            services, available_components
        )

        assert missing == []  # Returns empty for invalid services

    def test_validate_service_component_compatibility_success(self):
        """Test successful service-component compatibility validation."""
        services = ["auth"]
        components = ["backend", "frontend", "database"]

        errors = ServiceResolver.validate_service_component_compatibility(
            services, components
        )

        assert errors == []

    def test_validate_service_component_compatibility_missing(self):
        """Test service-component compatibility with missing components."""
        services = ["auth"]
        components = ["backend"]  # Missing database

        errors = ServiceResolver.validate_service_component_compatibility(
            services, components
        )

        assert len(errors) >= 1
        missing_errors = [e for e in errors if "requires component" in e]
        assert len(missing_errors) > 0

    def test_get_service_component_summary(self):
        """Test getting service component summary."""
        services = ["auth"]

        summary = ServiceResolver.get_service_component_summary(services)

        assert "auth" in summary
        assert "backend" in summary["auth"]
        assert "database" in summary["auth"]

    def test_get_service_component_summary_unknown(self):
        """Test getting service component summary for unknown service."""
        services = ["unknown_service"]

        summary = ServiceResolver.get_service_component_summary(services)

        assert "unknown_service" in summary
        assert summary["unknown_service"] == []

    def test_recommend_components_for_services(self):
        """Test getting recommended components for services."""
        # Create a test service with recommendations
        test_service = ServiceSpec(
            name="test_service",
            description="Test service with recommendations",
            required_components=["backend"],
            recommended_components=["redis", "worker"],
        )

        test_services = SERVICES.copy()
        test_services["test_service"] = test_service

        with mock.patch.dict(
            "aegis.core.service_resolver.SERVICES", test_services, clear=False
        ):
            recommendations = ServiceResolver.recommend_components_for_services(
                ["test_service"]
            )

            assert "redis" in recommendations
            assert "worker" in recommendations

    def test_recommend_components_for_services_empty(self):
        """Test getting recommendations for services without recommendations."""
        services = ["auth"]  # Auth service has no recommendations

        recommendations = ServiceResolver.recommend_components_for_services(services)

        assert recommendations == []

    def test_get_services_requiring_component(self):
        """Test getting services that require a specific component."""
        services = ServiceResolver.get_services_requiring_component("backend")

        assert "auth" in services  # Auth requires backend

    def test_get_services_requiring_component_none(self):
        """Test getting services for component that no service requires."""
        services = ServiceResolver.get_services_requiring_component(
            "nonexistent_component"
        )

        assert services == []

    def test_merge_service_and_component_selections(self):
        """Test merging service and component selections."""
        selected_services = ["auth"]
        selected_components = ["redis"]  # User also wants redis

        final_components, service_auto, component_auto = (
            ServiceResolver.merge_service_and_component_selections(
                selected_services, selected_components
            )
        )

        # Should have all required components
        assert "backend" in final_components
        assert "database" in final_components
        assert "redis" in final_components

        # Service auto-added should include auth requirements
        assert "backend" in service_auto
        assert "database" in service_auto

        # No component-to-component auto-adding for this case
        # (redis doesn't require other components)

    def test_merge_service_and_component_selections_overlapping(self):
        """Test merging when service and component selections overlap."""
        selected_services = ["auth"]  # Requires backend, database
        selected_components = [
            "backend",
            "worker",
        ]  # Backend overlaps, worker adds redis

        final_components, service_auto, component_auto = (
            ServiceResolver.merge_service_and_component_selections(
                selected_services, selected_components
            )
        )

        # Should have all components
        assert "backend" in final_components
        assert "database" in final_components
        assert "worker" in final_components
        assert "redis" in final_components

        # Service auto-added (backend overlaps with explicit, but database is auto)
        assert "database" in service_auto
        # Backend might or might not be in service_auto depending on deduplication logic

        # Component auto-added should include redis (required by worker)
        assert "redis" in component_auto

    def test_merge_empty_selections(self):
        """Test merging empty selections."""
        final_components, service_auto, component_auto = (
            ServiceResolver.merge_service_and_component_selections([], [])
        )

        assert final_components == []
        assert service_auto == []
        assert component_auto == []


class TestAIServiceBackend:
    """Test AI service bracket syntax and backend handling."""

    def test_validate_ai_service_memory_backend(self):
        """Test that ai[memory] is valid."""
        errors = ServiceResolver.validate_services(["ai[memory]"])
        assert errors == []

    def test_validate_ai_service_sqlite_backend(self):
        """Test that ai[sqlite] is valid."""
        errors = ServiceResolver.validate_services(["ai[sqlite]"])
        assert errors == []

    def test_validate_ai_service_invalid_backend(self):
        """Test that ai[invalid] is rejected."""
        errors = ServiceResolver.validate_services(["ai[invalid]"])
        assert len(errors) == 1
        # Error message changed from "Invalid backend" to "Unknown value" in ai parser
        assert "Unknown value" in errors[0] or "Invalid" in errors[0]
        assert "invalid" in errors[0]

    def test_validate_ai_service_no_bracket(self):
        """Test that plain 'ai' is valid (defaults to memory)."""
        errors = ServiceResolver.validate_services(["ai"])
        assert errors == []

    def test_resolve_ai_sqlite_adds_database(self):
        """Test that ai[sqlite] auto-adds database[sqlite] component."""
        services = ["ai[sqlite]"]

        resolved_components, auto_added = ServiceResolver.resolve_service_dependencies(
            services
        )

        # Should auto-add database with sqlite backend
        assert any("database" in c for c in resolved_components)
        assert any("database[sqlite]" in c for c in auto_added)

    def test_resolve_ai_memory_no_database(self):
        """Test that ai[memory] does NOT auto-add database."""
        services = ["ai[memory]"]

        resolved_components, auto_added = ServiceResolver.resolve_service_dependencies(
            services
        )

        # Should NOT add database for memory backend
        # AI service requires backend, which is core, but not database
        assert "database[sqlite]" not in auto_added
        assert not any("database" in c for c in auto_added)

    def test_resolve_ai_plain_no_database(self):
        """Test that plain 'ai' (defaults to memory) does NOT auto-add database."""
        services = ["ai"]

        resolved_components, auto_added = ServiceResolver.resolve_service_dependencies(
            services
        )

        # Plain ai defaults to memory, should NOT add database
        assert "database[sqlite]" not in auto_added

    def test_ai_sqlite_with_existing_database(self):
        """Test that ai[sqlite] doesn't duplicate database if already present."""
        services = ["ai[sqlite]"]

        resolved_components, auto_added = ServiceResolver.resolve_service_dependencies(
            services
        )

        # Database should appear only once
        database_count = sum(1 for c in resolved_components if c.startswith("database"))
        assert database_count == 1


class TestServiceResolverIntegration:
    """Integration tests for service resolver with real component system."""

    def test_auth_service_full_resolution(self):
        """Test complete auth service resolution flow."""
        # Start with just auth service
        services = ["auth"]

        # Resolve to components
        resolved_components, auto_added = ServiceResolver.resolve_service_dependencies(
            services
        )

        # Should have core components plus auth requirements
        assert "backend" in resolved_components
        assert "database" in resolved_components

        # Validate compatibility
        errors = ServiceResolver.validate_service_component_compatibility(
            services, resolved_components
        )
        assert errors == []

        # Get summary
        summary = ServiceResolver.get_service_component_summary(services)
        assert len(summary["auth"]) > 0

    def test_complex_service_component_merge(self):
        """Test complex scenario with multiple services and components."""
        # User wants auth service + explicit worker component
        services = ["auth"]
        components = ["worker"]  # Worker requires redis

        # Merge selections
        final_components, service_auto, component_auto = (
            ServiceResolver.merge_service_and_component_selections(services, components)
        )

        # Should have everything needed
        expected_components = {"backend", "database", "worker", "redis"}
        assert expected_components.issubset(set(final_components))

        # Validate final result is compatible
        errors = ServiceResolver.validate_service_component_compatibility(
            services, final_components
        )
        assert errors == []

    def test_service_resolver_edge_cases(self):
        """Test edge cases and error conditions."""
        # Invalid service
        with pytest.raises(ValueError):
            ServiceResolver.resolve_service_dependencies(["invalid_service"])

        # Empty inputs
        assert ServiceResolver.get_missing_components_for_services([], []) == []
        assert ServiceResolver.validate_services([]) == []
        assert ServiceResolver.get_service_component_summary([]) == {}
        assert ServiceResolver.recommend_components_for_services([]) == []


class TestInsightsServiceResolver:
    """Test insights service resolution and bracket validation."""

    def test_resolve_insights_dependencies(self):
        """Insights requires backend, database, and scheduler."""
        services = ["insights"]

        resolved, auto_added = ServiceResolver.resolve_service_dependencies(services)

        assert "backend" in resolved
        assert "database" in resolved
        assert "scheduler" in resolved

    def test_resolve_insights_recommends_worker(self):
        """Insights recommends worker component."""
        recommendations = ServiceResolver.recommend_components_for_services(
            ["insights"]
        )
        assert "worker" in recommendations

    def test_validate_insights_plain(self):
        """Plain 'insights' validates successfully."""
        errors = ServiceResolver.validate_services(["insights"])
        assert errors == []

    def test_validate_insights_with_brackets(self):
        """Bracket syntax validates successfully."""
        errors = ServiceResolver.validate_services(
            ["insights[github,pypi,plausible,reddit]"]
        )
        assert errors == []

    def test_validate_insights_invalid_source(self):
        """Invalid source in brackets fails validation."""
        errors = ServiceResolver.validate_services(["insights[github,invalid]"])
        assert len(errors) == 1
        assert "Invalid insights" in errors[0]

    def test_insights_full_resolution(self):
        """Full resolution flow for insights service."""
        services = ["insights"]

        resolved, _ = ServiceResolver.resolve_service_dependencies(services)

        errors = ServiceResolver.validate_service_component_compatibility(
            services, resolved
        )
        assert errors == []

    def test_insights_with_auth_merge(self):
        """Insights + auth share backend and database — no duplication."""
        services = ["insights", "auth"]

        resolved, _ = ServiceResolver.resolve_service_dependencies(services)

        # Both need backend/database, should appear once
        assert resolved.count("backend") == 1
        assert resolved.count("database") == 1
        assert "scheduler" in resolved

    def test_insights_per_user_requires_auth(self):
        """``insights[per_user]`` without auth at all fails validation."""
        errors = ServiceResolver.validate_services(["insights[per_user]"])
        assert any("per_user" in e and "auth" in e for e in errors)

    def test_insights_per_user_requires_auth_org_not_basic(self):
        """``insights[per_user]`` + ``auth[basic]`` fails: the per-user
        variant FKs to organization.id which only auth[org] ships."""
        errors = ServiceResolver.validate_services(
            ["auth[basic]", "insights[per_user]"]
        )
        assert errors, "expected an error for auth[basic] + insights[per_user]"
        assert any("auth[org]" in e for e in errors)

    def test_insights_per_user_requires_auth_org_not_rbac(self):
        """``insights[per_user]`` + ``auth[rbac]`` also fails — rbac
        doesn't ship the organization table either."""
        errors = ServiceResolver.validate_services(["auth[rbac]", "insights[per_user]"])
        assert errors
        assert any("auth[org]" in e for e in errors)

    def test_insights_per_user_with_auth_org_validates(self):
        """``insights[per_user]`` + ``auth[org]`` is the supported
        combination — validates clean."""
        errors = ServiceResolver.validate_services(["auth[org]", "insights[per_user]"])
        assert errors == []

    def test_insights_per_user_with_bare_auth_defaults_to_basic(self):
        """Bare ``auth`` (no brackets) defaults to basic, so it must
        still fail the org-level requirement."""
        errors = ServiceResolver.validate_services(["auth", "insights[per_user]"])
        assert errors
        assert any("auth[org]" in e for e in errors)


class TestBlogServiceResolver:
    """Test blog service resolution."""

    def test_resolve_blog_dependencies(self):
        """Blog requires backend and database."""
        services = ["blog"]

        resolved, auto_added = ServiceResolver.resolve_service_dependencies(services)

        assert "backend" in resolved
        assert "database" in resolved
        assert "backend" in auto_added
        assert "database" in auto_added

    def test_validate_blog_plain(self):
        """Plain 'blog' validates successfully."""
        errors = ServiceResolver.validate_services(["blog"])
        assert errors == []

    def test_blog_full_resolution(self):
        """Full resolution flow for blog service."""
        services = ["blog"]

        resolved, _ = ServiceResolver.resolve_service_dependencies(services)

        errors = ServiceResolver.validate_service_component_compatibility(
            services, resolved
        )
        assert errors == []

    def test_blog_with_auth_merge(self):
        """Blog + auth share backend and database without duplication."""
        services = ["blog", "auth"]

        resolved, _ = ServiceResolver.resolve_service_dependencies(services)

        assert resolved.count("backend") == 1
        assert resolved.count("database") == 1
