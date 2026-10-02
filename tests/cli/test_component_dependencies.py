"""
Component Dependency Validation Tests for Aegis Stack CLI.

This module tests the component dependency resolution system to ensure:
1. Hard dependencies are automatically included
2. Dependency conflicts are properly detected
3. Component specifications are correctly applied
4. Generated projects have the right dependencies

Tests the core logic in aegis.core.dependency_resolver and ensures
component combinations work as expected.
"""

import pytest

from aegis.core.components import COMPONENTS, ComponentSpec, ComponentType
from aegis.core.dependency_resolver import DependencyResolver

from .conftest import ProjectFactory


class DependencyTestCase:
    """Test case for component dependency validation."""

    def __init__(
        self,
        name: str,
        requested_components: list[str],
        expected_resolved: list[str],
        description: str,
    ):
        self.name = name
        self.requested_components = requested_components
        self.expected_resolved = expected_resolved
        self.description = description


# Test cases for dependency resolution
DEPENDENCY_TEST_CASES = [
    DependencyTestCase(
        name="base_only",
        requested_components=[],
        expected_resolved=[],  # Core components (backend, frontend) are always included
        description="Base stack with no additional components",
    ),
    DependencyTestCase(
        name="redis_explicit",
        requested_components=["redis"],
        expected_resolved=["redis"],
        description="Explicitly requesting Redis",
    ),
    DependencyTestCase(
        name="scheduler_standalone",
        requested_components=["scheduler"],
        expected_resolved=["scheduler"],
        description="Scheduler runs standalone without Redis dependency",
    ),
    DependencyTestCase(
        name="worker_includes_redis",
        requested_components=["worker"],
        expected_resolved=["redis", "worker"],
        description="Worker automatically includes Redis dependency",
    ),
    DependencyTestCase(
        name="full_stack",
        requested_components=["worker", "scheduler"],
        expected_resolved=["redis", "worker", "scheduler"],
        description="Full stack resolves all dependencies without duplicates",
    ),
    DependencyTestCase(
        name="redundant_redis",
        requested_components=["redis", "worker"],
        expected_resolved=["redis", "worker"],
        description="Explicitly including Redis with worker doesn't duplicate",
    ),
    DependencyTestCase(
        name="mixed_dependencies",
        requested_components=["worker", "scheduler"],
        expected_resolved=["redis", "worker", "scheduler"],
        description=(
            "Mix of Redis-dependent (worker) and standalone (scheduler) components"
        ),
    ),
]


@pytest.fixture
def dependency_resolver() -> DependencyResolver:
    """Create a dependency resolver for testing."""
    return DependencyResolver()


def test_component_registry_structure() -> None:
    """Test that component registry has expected structure."""
    # Verify core components exist
    component_names = set(COMPONENTS.keys())
    expected_core = {
        "redis",
        "worker",
        "scheduler",
    }  # Current infrastructure components

    assert expected_core.issubset(component_names), (
        f"Missing expected components. "
        f"Expected: {expected_core}, "
        f"Got: {component_names}"
    )

    # Verify all components have required fields
    for name, spec in COMPONENTS.items():
        assert isinstance(spec, ComponentSpec)
        assert spec.name == name
        assert isinstance(spec.type, ComponentType)
        assert isinstance(spec.description, str)
        assert len(spec.description) > 0


def test_worker_component_specification() -> None:
    """Test that worker component is properly specified."""
    worker_spec = COMPONENTS["worker"]

    # Worker should be infrastructure type
    assert worker_spec.type == ComponentType.INFRASTRUCTURE

    # Worker should require Redis
    requires = worker_spec.requires
    assert requires is not None and "redis" in requires

    # Worker should have arq dependency
    pyproject_deps = worker_spec.pyproject_deps
    assert pyproject_deps is not None and any("arq" in dep for dep in pyproject_deps)

    # Worker should have Docker services
    docker_services = worker_spec.docker_services
    assert docker_services is not None and any(
        "worker" in service for service in docker_services
    )

    # Worker should have template files
    template_files = worker_spec.template_files
    assert template_files is not None and any(
        "worker" in file for file in template_files
    )


def test_scheduler_component_specification() -> None:
    """Test that scheduler component is properly specified."""
    scheduler_spec = COMPONENTS["scheduler"]

    # Scheduler should be infrastructure type
    assert scheduler_spec.type == ComponentType.INFRASTRUCTURE

    # Scheduler should not require other components
    requires = scheduler_spec.requires
    assert requires is not None and not requires

    # Scheduler should have APScheduler dependency
    pyproject_deps = scheduler_spec.pyproject_deps
    assert pyproject_deps is not None and any(
        "apscheduler" in dep for dep in pyproject_deps
    )


def test_redis_component_specification() -> None:
    """Test that Redis component is properly specified."""
    redis_spec = COMPONENTS["redis"]

    # Redis should be infrastructure type
    assert redis_spec.type == ComponentType.INFRASTRUCTURE

    # Redis should not require other components (it's a base dependency)
    requires = redis_spec.requires
    assert requires is not None and not requires

    # Redis should have redis dependency
    pyproject_deps = redis_spec.pyproject_deps
    assert pyproject_deps is not None and any("redis" in dep for dep in pyproject_deps)


@pytest.mark.parametrize("test_case", DEPENDENCY_TEST_CASES, ids=lambda x: x.name)
def test_dependency_resolution(
    test_case: DependencyTestCase, dependency_resolver: DependencyResolver
) -> None:
    """Test dependency resolution logic."""
    resolved = dependency_resolver.resolve_dependencies(test_case.requested_components)

    # Convert to sets for comparison (order doesn't matter)
    resolved_set = set(resolved)
    expected_set = set(test_case.expected_resolved)

    assert resolved_set == expected_set, (
        f"Dependency resolution failed for {test_case.description}\n"
        f"Requested: {test_case.requested_components}\n"
        f"Expected: {sorted(test_case.expected_resolved)}\n"
        f"Got: {sorted(resolved)}\n"
        f"Missing: {sorted(expected_set - resolved_set)}\n"
        f"Extra: {sorted(resolved_set - expected_set)}"
    )


def test_dependency_resolution_order() -> None:
    """Test that dependencies are resolved in correct order."""
    resolver = DependencyResolver()

    resolved = resolver.resolve_dependencies(["worker", "scheduler"])

    redis_index = resolved.index("redis")
    worker_index = resolved.index("worker")

    assert redis_index < worker_index, "Redis should come before worker"


def test_circular_dependency_detection() -> None:
    """Test that circular dependencies are detected (if any exist)."""
    # Current components don't have circular dependencies, but test the logic
    resolver = DependencyResolver()

    # This should work without infinite recursion
    resolved = resolver.resolve_dependencies(["worker", "scheduler", "redis"])

    # Should not have duplicates
    assert len(resolved) == len(set(resolved)), (
        "Resolved dependencies contain duplicates"
    )


def test_invalid_component_handling() -> None:
    """Test handling of invalid component names."""
    resolver = DependencyResolver()

    # Should raise appropriate error for invalid component
    with pytest.raises((KeyError, ValueError)):
        resolver.resolve_dependencies(["invalid_component"])


@pytest.mark.parametrize("test_case", DEPENDENCY_TEST_CASES, ids=lambda x: x.name)
def test_generated_project_dependencies(
    test_case: DependencyTestCase, project_factory: ProjectFactory
) -> None:
    """Test that generated projects have correct dependencies resolved."""
    if not test_case.requested_components:
        # Skip base-only test for project generation
        pytest.skip("Base-only test doesn't need project generation validation")

    # A cached project: the same component set is generated once per session
    # and shared, where a fresh init per case was 10-15s each.
    project_path = project_factory(components=test_case.requested_components)
    pyproject_path = project_path / "pyproject.toml"
    assert pyproject_path.exists(), "pyproject.toml not found"

    pyproject_content = pyproject_path.read_text()

    # Verify all expected components have their dependencies
    expected_resolved = test_case.expected_resolved
    if expected_resolved is not None:
        for component_name in expected_resolved:
            if component_name in COMPONENTS:
                component_spec = COMPONENTS[component_name]

                # Check that component's pyproject dependencies are present
                pyproject_deps = component_spec.pyproject_deps
                if pyproject_deps is not None:
                    for dep in pyproject_deps:
                        # Extract base package name (before version specifiers)
                        base_dep = dep.split(">=")[0].split("==")[0].split("[")[0]

                        assert (
                            f'"{base_dep}' in pyproject_content
                            or f"'{base_dep}" in pyproject_content
                        ), (
                            f"Missing dependency '{base_dep}' for component "
                            f"'{component_name}' in generated project pyproject.toml"
                        )


@pytest.mark.parametrize("test_case", DEPENDENCY_TEST_CASES, ids=lambda x: x.name)
def test_generated_project_docker_services(
    test_case: DependencyTestCase, project_factory: ProjectFactory
) -> None:
    """Test that generated projects have correct Docker services."""
    if not test_case.requested_components:
        # Skip base-only test
        pytest.skip("Base-only test doesn't need Docker service validation")

    project_path = project_factory(components=test_case.requested_components)
    docker_compose_path = project_path / "docker-compose.yml"
    assert docker_compose_path.exists(), "docker-compose.yml not found"

    docker_compose_content = docker_compose_path.read_text()

    # Verify all expected components have their Docker services
    expected_resolved = test_case.expected_resolved
    if expected_resolved is not None:
        for component_name in expected_resolved:
            if component_name in COMPONENTS:
                component_spec = COMPONENTS[component_name]

                # Check that component's Docker services are present
                docker_services = component_spec.docker_services
                if docker_services is not None:
                    for service in docker_services:
                        assert f"{service}:" in docker_compose_content, (
                            f"Missing Docker service '{service}' for component "
                            f"'{component_name}' in generated docker-compose.yml"
                        )


def test_dependency_resolver_edge_cases() -> None:
    """Test edge cases in dependency resolution."""
    resolver = DependencyResolver()

    # Empty list should work
    resolved = resolver.resolve_dependencies([])
    assert resolved == []

    # Single component should work
    resolved = resolver.resolve_dependencies(["redis"])
    assert resolved == ["redis"]

    # Duplicate components should be deduplicated
    resolved = resolver.resolve_dependencies(["redis", "redis"])
    assert resolved == ["redis"]


def test_component_metadata_consistency() -> None:
    """Test that component metadata is consistent."""
    for name, spec in COMPONENTS.items():
        # All required dependencies should exist in registry
        requires = spec.requires
        if requires is not None:
            for required_component in requires:
                assert required_component in COMPONENTS, (
                    f"Component '{name}' requires '{required_component}' "
                    f"which is not in the component registry"
                )

        # Component name should match registry key
        assert spec.name == name

        # All lists should be initialized (not None)
        assert spec.requires is not None
        assert spec.pyproject_deps is not None
        assert spec.docker_services is not None
        assert spec.template_files is not None


def test_infrastructure_component_types() -> None:
    """Test that infrastructure components are properly categorized."""
    infrastructure_components = {
        name: spec
        for name, spec in COMPONENTS.items()
        if spec.type == ComponentType.INFRASTRUCTURE
    }

    # Should include our expected infrastructure components
    expected_infra = {"redis", "worker", "scheduler", "database"}
    actual_infra = set(infrastructure_components.keys())

    assert expected_infra.issubset(actual_infra), (
        f"Missing expected infrastructure components. "
        f"Expected: {expected_infra}, "
        f"Got: {actual_infra}"
    )


def test_dependency_resolution_performance() -> None:
    """Test that dependency resolution is performant."""
    import time

    resolver = DependencyResolver()

    # Should resolve complex dependencies quickly
    start_time = time.time()

    for _ in range(100):
        resolver.resolve_dependencies(["worker", "scheduler"])

    duration = time.time() - start_time

    # Should complete 100 resolutions in under 1 second
    assert duration < 1.0, (
        f"Dependency resolution too slow: {duration:.3f}s for 100 iterations"
    )


def test_interactive_selection_registry_sync() -> None:
    """Test that interactive selection includes every optional component."""
    from aegis.cli.interactive import get_interactive_infrastructure_components

    # Get components from registry
    infra_components = get_interactive_infrastructure_components()
    infra_names = {comp.name for comp in infra_components}

    # Every non-CORE component (infrastructure or frontend) is selectable
    registry_infra_names = {
        name for name, spec in COMPONENTS.items() if spec.type != ComponentType.CORE
    }

    # Interactive selection should include all optional components
    assert infra_names == registry_infra_names, (
        f"Interactive selection components ({infra_names}) don't match "
        f"registry optional components ({registry_infra_names}). "
        f"Missing from interactive: {registry_infra_names - infra_names}, "
        f"Extra in interactive: {infra_names - registry_infra_names}"
    )

    # Should include database component (our recent addition)
    assert "database" in infra_names, (
        "Database component should be available in interactive selection"
    )

    # Should include all expected components
    expected_components = {"redis", "worker", "scheduler", "database"}
    assert expected_components.issubset(infra_names), (
        f"Missing expected components from interactive selection. "
        f"Expected: {expected_components}, Got: {infra_names}"
    )


def test_interactive_selection_component_ordering() -> None:
    """Test that interactive selection returns components in consistent order."""
    from aegis.cli.interactive import get_interactive_infrastructure_components

    # Get components multiple times
    components1 = get_interactive_infrastructure_components()
    components2 = get_interactive_infrastructure_components()

    # Should be identical (same order)
    names1 = [comp.name for comp in components1]
    names2 = [comp.name for comp in components2]

    assert names1 == names2, f"Component ordering not consistent: {names1} vs {names2}"

    # Should be sorted alphabetically
    sorted_names = sorted(names1)
    assert names1 == sorted_names, (
        f"Components not in alphabetical order: {names1}, expected: {sorted_names}"
    )
