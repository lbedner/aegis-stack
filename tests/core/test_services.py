"""
Tests for service registry and specifications.

Tests the core service infrastructure including ServiceSpec,
ServiceType enum, and service registry operations.
"""

import pytest

from aegis.core.services import (
    SERVICES,
    ServiceSpec,
    ServiceType,
    get_service,
    get_service_dependencies,
    get_services_by_type,
    list_available_services,
    validate_service_dependencies,
)


class TestServiceType:
    """Test ServiceType enum."""

    def test_service_type_values(self):
        """Test that ServiceType has expected values."""
        assert ServiceType.AUTH.value == "auth"
        assert ServiceType.PAYMENT.value == "payment"
        assert ServiceType.AI.value == "ai"
        assert ServiceType.NOTIFICATION.value == "notification"
        assert ServiceType.ANALYTICS.value == "analytics"
        assert ServiceType.STORAGE.value == "storage"
        assert ServiceType.CONTENT.value == "content"
        assert ServiceType.FINANCE.value == "finance"

    def test_service_type_enum_completeness(self):
        """Test that we have all expected service types."""
        expected_types = {
            "auth",
            "payment",
            "ai",
            "notification",
            "analytics",
            "storage",
            "content",
            "finance",
        }
        actual_types = {st.value for st in ServiceType}
        assert actual_types == expected_types


class TestServiceSpec:
    """Test ServiceSpec dataclass."""

    def test_service_spec_creation(self):
        """Test creating a ServiceSpec with all fields."""
        spec = ServiceSpec(
            name="test_service",
            type=ServiceType.AUTH,
            description="Test service description",
            required_components=["backend", "database"],
            recommended_components=["redis"],
            required_services=["auth"],
            conflicts=["other_service"],
            pyproject_deps=["test-package==1.0.0"],
            template_files=["app/services/test/"],
        )

        assert spec.name == "test_service"
        assert spec.type == ServiceType.AUTH
        assert spec.description == "Test service description"
        assert spec.required_components == ["backend", "database"]
        assert spec.recommended_components == ["redis"]
        assert spec.required_services == ["auth"]
        assert spec.conflicts == ["other_service"]
        assert spec.pyproject_deps == ["test-package==1.0.0"]
        assert spec.template_files == ["app/services/test/"]

    def test_service_spec_minimal_creation(self):
        """Test creating a ServiceSpec with only required fields."""
        spec = ServiceSpec(
            name="minimal_service",
            type=ServiceType.PAYMENT,
            description="Minimal service",
        )

        assert spec.name == "minimal_service"
        assert spec.type == ServiceType.PAYMENT
        assert spec.description == "Minimal service"
        assert spec.required_components == []
        assert spec.recommended_components == []
        assert spec.required_services == []
        assert spec.conflicts == []
        assert spec.pyproject_deps == []
        assert spec.template_files == []

    def test_service_spec_defaults(self):
        """Test that default_factory creates empty lists for optional fields."""
        spec = ServiceSpec(
            name="test",
            type=ServiceType.AI,
            description="Test",
        )

        # All optional fields should be initialized to empty lists
        assert spec.required_components == []
        assert spec.recommended_components == []
        assert spec.required_services == []
        assert spec.conflicts == []
        assert spec.pyproject_deps == []
        assert spec.template_files == []


class TestServicesRegistry:
    """Test the SERVICES registry and related functions."""

    def test_services_registry_not_empty(self):
        """Test that the SERVICES registry contains services."""
        assert len(SERVICES) > 0
        assert "auth" in SERVICES
        assert "blog" in SERVICES
        assert "insights" in SERVICES
        assert "finance" in SERVICES

    def test_insights_service_specification(self):
        """Test the insights service specification is properly defined."""
        spec = SERVICES["insights"]

        assert spec.name == "insights"
        assert spec.type == ServiceType.ANALYTICS
        assert spec.description
        assert "backend" in spec.required_components
        assert "database" in spec.required_components
        assert "scheduler" in spec.required_components
        assert "worker" in spec.recommended_components
        assert len(spec.pyproject_deps) > 0
        assert len(spec.template_files) > 0

    def test_insights_uses_component_constants(self):
        """Test that insights spec uses ComponentNames, not magic strings."""
        from aegis.constants import ComponentNames

        spec = SERVICES["insights"]
        assert ComponentNames.BACKEND in spec.required_components
        assert ComponentNames.DATABASE in spec.required_components
        assert ComponentNames.SCHEDULER in spec.required_components
        assert ComponentNames.WORKER in spec.recommended_components

    def test_auth_service_specification(self):
        """Test the auth service specification is properly defined."""
        auth_spec = SERVICES["auth"]

        assert auth_spec.name == "auth"
        assert auth_spec.type == ServiceType.AUTH
        assert auth_spec.description
        assert "backend" in auth_spec.required_components
        assert "database" in auth_spec.required_components
        assert len(auth_spec.pyproject_deps) > 0
        assert len(auth_spec.template_files) > 0

    def test_auth_service_dependencies(self):
        """Test that auth service has expected dependencies."""
        auth_spec = SERVICES["auth"]

        # Should require backend and database
        assert "backend" in auth_spec.required_components
        assert "database" in auth_spec.required_components

        # Should have authentication-related dependencies. ``passlib`` was
        # replaced by ``bcrypt`` in the template — the spec mirrors that.
        deps_str = " ".join(auth_spec.pyproject_deps)
        assert "python-jose" in deps_str
        assert "bcrypt" in deps_str

    def test_auth_service_template_files(self):
        """Test that auth service specifies template files."""
        auth_spec = SERVICES["auth"]

        expected_patterns = [
            "app/components/backend/api/auth/",
            "app/models/user.py",
            "app/services/auth/",
            "app/core/security.py",
        ]

        for pattern in expected_patterns:
            assert pattern in auth_spec.template_files

    def test_payment_service_specification(self):
        """Test the payment service specification is properly defined."""
        spec = SERVICES["payment"]

        assert spec.name == "payment"
        assert spec.type == ServiceType.PAYMENT
        assert spec.description
        assert "backend" in spec.required_components
        assert "database" in spec.required_components
        assert "worker" in spec.recommended_components
        assert len(spec.pyproject_deps) > 0
        assert len(spec.template_files) > 0

    def test_payment_uses_component_constants(self):
        """Test that payment spec uses ComponentNames, not magic strings."""
        from aegis.constants import ComponentNames

        spec = SERVICES["payment"]
        assert ComponentNames.BACKEND in spec.required_components
        assert ComponentNames.DATABASE in spec.required_components
        assert ComponentNames.WORKER in spec.recommended_components

    def test_finance_service_specification(self):
        """Test the finance service specification is properly defined.

        The spec ships template file paths and its migration specs
        (FINANCE_MIGRATION + conditional FINANCE_AUTH_LINK_MIGRATION); runtime
        wiring and pyproject deps are added by later tickets. Assert only what
        the spec currently establishes.
        """
        spec = SERVICES["finance"]

        assert spec.name == "finance"
        assert spec.type == ServiceType.FINANCE
        assert spec.description
        assert "backend" in spec.required_components
        assert "database" in spec.required_components
        assert "scheduler" in spec.required_components
        assert "worker" in spec.recommended_components
        # Auth is integrated-when-present, not required — finance runs
        # standalone (single-user) and links owner FKs only when auth ships.
        assert spec.required_services == []
        assert len(spec.template_files) > 0

    def test_finance_uses_component_constants(self):
        """Test that finance spec uses ComponentNames, not magic strings."""
        from aegis.constants import ComponentNames

        spec = SERVICES["finance"]
        assert ComponentNames.BACKEND in spec.required_components
        assert ComponentNames.DATABASE in spec.required_components
        assert ComponentNames.SCHEDULER in spec.required_components
        assert ComponentNames.WORKER in spec.recommended_components

    def test_blog_service_specification(self):
        """Test the blog service specification is properly defined."""
        from aegis.constants import ComponentNames

        spec = SERVICES["blog"]

        assert spec.name == "blog"
        assert spec.type == ServiceType.CONTENT
        assert spec.description
        assert ComponentNames.BACKEND in spec.required_components
        assert ComponentNames.DATABASE in spec.required_components
        assert len(spec.template_files) > 0
        assert spec.migrations

    def test_blog_service_wiring(self):
        """Test that blog publishes its backend and dashboard wiring."""
        spec = SERVICES["blog"]

        assert len(spec.wiring.routers) == 1
        assert spec.wiring.routers[0].module == "app.components.backend.api.blog.router"
        assert spec.wiring.routers[0].alias == "blog_router"
        assert spec.wiring.routers[0].prefix == "/api/v1"
        assert len(spec.wiring.dashboard_cards) == 1
        assert spec.wiring.dashboard_cards[0].modal_id == "service_blog"
        assert len(spec.wiring.dashboard_modals) == 1
        assert spec.wiring.dashboard_modals[0].modal_id == "service_blog"

    def test_documents_service_wiring(self):
        """Documents ships a card and a modal like every other service."""
        spec = SERVICES["documents"]

        assert spec.wiring.dashboard_cards[0].modal_id == "service_documents"
        assert spec.wiring.dashboard_modals[0].modal_id == "service_documents"
        assert (
            "app/components/frontend/dashboard/cards/documents_card.py"
            in spec.files.primary
        )
        assert (
            "app/components/frontend/dashboard/modals/documents_modal.py"
            in spec.files.primary
        )


class TestServiceRegistryFunctions:
    """Test service registry helper functions."""

    def test_get_service_success(self):
        """Test getting an existing service."""
        service = get_service("auth")
        assert service.name == "auth"
        assert service.type == ServiceType.AUTH

    def test_get_service_unknown(self):
        """Test getting an unknown service raises ValueError."""
        with pytest.raises(ValueError, match="Unknown service: nonexistent"):
            get_service("nonexistent")

    def test_get_services_by_type(self):
        """Test filtering services by type."""
        auth_services = get_services_by_type(ServiceType.AUTH)
        assert "auth" in auth_services
        assert all(spec.type == ServiceType.AUTH for spec in auth_services.values())

        storage_services = get_services_by_type(ServiceType.STORAGE)
        assert "documents" in storage_services
        assert all(
            spec.type == ServiceType.STORAGE for spec in storage_services.values()
        )

        # Every declared type is claimed by at least one service: a type
        # nobody uses is a category we invented and never filled, and the
        # filter should not be tested against one that cannot occur.
        for service_type in ServiceType:
            assert get_services_by_type(service_type), service_type

        content_services = get_services_by_type(ServiceType.CONTENT)
        assert "blog" in content_services
        assert all(
            spec.type == ServiceType.CONTENT for spec in content_services.values()
        )

    def test_list_available_services(self):
        """Test listing all available services."""
        services = list_available_services()
        assert isinstance(services, list)
        assert "auth" in services
        assert len(services) == len(SERVICES)

    def test_get_service_dependencies(self):
        """Test getting service dependencies."""
        # Auth service should return its required components
        auth_deps = get_service_dependencies("auth")
        assert "backend" in auth_deps
        assert "database" in auth_deps

        # Unknown service should return empty list
        unknown_deps = get_service_dependencies("nonexistent")
        assert unknown_deps == []

    def test_get_service_dependencies_immutable(self):
        """Test that get_service_dependencies returns a copy."""
        deps1 = get_service_dependencies("auth")
        deps2 = get_service_dependencies("auth")

        # Should be equal but not the same object
        assert deps1 == deps2
        assert deps1 is not deps2

        # Modifying one shouldn't affect the other
        deps1.append("test")
        assert deps1 != deps2


class TestServiceValidation:
    """Test service dependency validation."""

    def test_validate_service_dependencies_success(self):
        """Test successful validation with all dependencies met."""
        selected_services = ["auth"]
        available_components = ["backend", "frontend", "database"]

        errors = validate_service_dependencies(selected_services, available_components)
        assert errors == []

    def test_validate_service_dependencies_missing_component(self):
        """Test validation failure when required component is missing."""
        selected_services = ["auth"]
        available_components = ["backend"]  # Missing database

        errors = validate_service_dependencies(selected_services, available_components)
        assert len(errors) == 1
        assert "auth" in errors[0]
        assert "database" in errors[0]

    def test_validate_service_dependencies_unknown_service(self):
        """Test validation failure for unknown service."""
        selected_services = ["nonexistent"]
        available_components = ["backend", "database"]

        errors = validate_service_dependencies(selected_services, available_components)
        assert len(errors) == 1
        assert "Unknown service: nonexistent" in errors[0]

    def test_validate_service_dependencies_multiple_errors(self):
        """Test validation with multiple errors."""
        selected_services = ["auth", "nonexistent"]
        available_components = ["backend"]  # Missing database for auth

        errors = validate_service_dependencies(selected_services, available_components)
        assert len(errors) == 2

        # Should have both unknown service and missing component errors
        error_text = " ".join(errors)
        assert "Unknown service: nonexistent" in error_text
        assert "database" in error_text

    def test_validate_service_dependencies_empty_inputs(self):
        """Test validation with empty inputs."""
        # Empty services should pass
        errors = validate_service_dependencies([], ["backend"])
        assert errors == []

        # Empty components with services should fail
        errors = validate_service_dependencies(["auth"], [])
        assert len(errors) >= 1

    def test_service_conflicts_validation(self):
        """Test validation of service conflicts (when implemented)."""
        # Create a test spec with conflicts
        test_spec = ServiceSpec(
            name="test_conflict",
            type=ServiceType.AUTH,
            description="Test conflict service",
            conflicts=["auth"],
        )

        # Use mock to temporarily add test service to registry
        from unittest import mock

        # Create a temporary registry with the test service
        test_services = SERVICES.copy()
        test_services["test_conflict"] = test_spec

        # Mock the SERVICES dict during validation
        with mock.patch.dict(
            "aegis.core.services.SERVICES", test_services, clear=False
        ):
            # Should detect conflict
            errors = validate_service_dependencies(
                ["auth", "test_conflict"], ["backend", "database"]
            )

            # Should have conflict error
            conflict_errors = [e for e in errors if "conflicts with" in e]
            assert len(conflict_errors) > 0


class TestServiceRegistryIntegrity:
    """Test integrity and consistency of the service registry."""

    def test_all_services_have_valid_types(self):
        """Test that all services have valid ServiceType values."""
        for _name, spec in SERVICES.items():
            assert isinstance(spec.type, ServiceType)

    def test_all_services_have_descriptions(self):
        """Test that all services have non-empty descriptions."""
        for _name, spec in SERVICES.items():
            assert spec.description
            assert len(spec.description.strip()) > 0

    def test_service_names_match_keys(self):
        """Test that service spec names match their registry keys."""
        for key, spec in SERVICES.items():
            assert spec.name == key

    def test_no_circular_dependencies(self):
        """Test that services don't have circular dependencies."""
        # This is a basic check - could be expanded for complex scenarios
        for name, spec in SERVICES.items():
            assert name not in spec.required_services

    def test_required_components_are_strings(self):
        """Test that all required components are strings."""
        for _name, spec in SERVICES.items():
            for component in spec.required_components:
                assert isinstance(component, str)
                assert component.strip() == component  # No leading/trailing whitespace
                assert len(component) > 0  # Non-empty

    def test_pyproject_deps_format(self):
        """Test that pyproject dependencies follow expected format."""
        for _name, spec in SERVICES.items():
            for dep in spec.pyproject_deps:
                assert isinstance(dep, str)
                assert len(dep) > 0
                # Should contain package name (basic format check)
                assert not dep.startswith("=")
                assert not dep.startswith("<")
                assert not dep.startswith(">")
