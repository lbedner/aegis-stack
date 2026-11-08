"""
Service dependency resolution for Aegis Stack.

This module handles service dependency resolution, converting service selections
to their required components and validating service-to-component compatibility.
"""

from ..constants import AnswerKeys, AuthLevels
from ..i18n import t
from .ai_service_parser import evals_rule
from .component_utils import extract_base_component_name, extract_base_service_name
from .dependency_resolver import DependencyResolver
from .option_spec import (
    compute_auto_requires,
    is_spec_with_options,
    parse_options,
    variant_answers,
)
from .services import SERVICES, get_service_dependencies


def _normalise_bracket_variants(components: set[str]) -> set[str]:
    """Drop plain ``name`` when ``name[variant]`` is also present.

    e.g. ``{"backend", "database", "database[postgres]"}`` becomes
    ``{"backend", "database[postgres]"}``. Pre-R3 this was an
    auth-specific ``discard("database")`` step inside the resolver;
    R3 generalises it so any spec with bracket-variant auto_requires
    works without the resolver having per-service knowledge.
    """
    bracketed_bases = {extract_base_component_name(c) for c in components if "[" in c}
    return {c for c in components if "[" in c or c not in bracketed_bases}


class ServiceResolver:
    """Handles service dependency resolution and validation."""

    @staticmethod
    def resolve_service_dependencies(
        selected_services: list[str],
    ) -> tuple[list[str], list[str]]:
        """
        Resolve services to their required components.

        Args:
            selected_services: List of service names selected by user
                              (may include bracket syntax like ai[sqlite])

        Returns:
            Tuple of (resolved_components, service_added_components)
            - resolved_components: All components needed (including auto-added)
            - service_added_components: Components that were added due to services

        Raises:
            ValueError: If any selected services are invalid
        """
        # Validate services first
        errors = ServiceResolver.validate_services(selected_services)
        if errors:
            raise ValueError(f"Invalid services: {'; '.join(errors)}")

        # Collect all components required by services
        service_required_components: set[str] = set()
        for service in selected_services:
            # Extract base service name (strip bracket info)
            base_service = extract_base_service_name(service)
            service_deps = get_service_dependencies(base_service)
            service_required_components.update(service_deps)

            # R3: bracket-syntax options can declare auto_requires rules on
            # their OptionSpec. Parse the spec string and let each option
            # contribute components to add. Replaces the per-service
            # if-blocks (AI persistence-backend → database[backend]; auth
            # engine override → database[engine]).
            spec = SERVICES.get(base_service)
            if spec is not None and is_spec_with_options(service):
                parsed = parse_options(service, spec)
                service_required_components.update(compute_auto_requires(spec, parsed))

        # When a bracket-variant component (e.g. database[postgres]) is
        # present, drop the plain base name (e.g. database) — they describe
        # the same component, and the variant wins. This generalises the
        # previous auth-specific "discard then add" pattern.
        service_required_components = _normalise_bracket_variants(
            service_required_components
        )

        # Convert to list and resolve component-to-component dependencies
        component_list = list(service_required_components)
        resolved_components = DependencyResolver.resolve_dependencies(component_list)

        # The service_added_components are what services directly require
        # (This represents what gets auto-added when services are selected)
        service_added_components = sorted(service_required_components)

        return resolved_components, service_added_components

    @staticmethod
    def validate_services(services: list[str]) -> list[str]:
        """
        Validate service selection and return errors.

        Args:
            services: List of service names to validate
                     (may include bracket syntax like ai[langchain, sqlite, openai])

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Extract base names for all services (strip bracket info)
        base_services = [extract_base_service_name(s) for s in services]

        for service in services:
            base_service = extract_base_service_name(service)
            if base_service not in SERVICES:
                errors.append(t("validation.unknown_service", name=base_service))
                continue

            spec = SERVICES[base_service]

            # Generic bracket-syntax validation (R3): any service that has
            # bracket-syntax options gets validated up-front, so
            # resolve_service_dependencies() can call parse_options() without
            # raising mid-resolution. Pre-R3 this was per-service (AI and
            # insights had explicit blocks; auth's parse errors leaked
            # through). Choice validation (e.g. "backend must be memory /
            # sqlite / postgres") is now handled inside parse_options
            # itself, which is why no service-specific checks remain here.
            if is_spec_with_options(service):
                try:
                    parse_options(service, spec)
                except ValueError as e:
                    errors.append(f"Invalid {base_service} service syntax: {e}")
                else:
                    if rule := evals_rule(variant_answers(service, spec)):
                        errors.append(rule)

            # Check service conflicts
            if spec.conflicts:
                for conflict in spec.conflicts:
                    if conflict in base_services:
                        errors.append(
                            f"Service '{base_service}' conflicts with "
                            f"service '{conflict}'"
                        )

        # Check for service-to-service dependencies
        for service in services:
            base_service = extract_base_service_name(service)
            if base_service not in SERVICES:
                continue  # Already reported above

            spec = SERVICES[base_service]
            if spec.required_services:
                for required_service in spec.required_services:
                    if required_service not in base_services:
                        errors.append(
                            f"Service '{base_service}' requires "
                            f"service '{required_service}'"
                        )

        # Conditional service-to-service dependency: ``insights[per_user]``
        # generates a ``project`` table that FKs to ``user.id`` and
        # ``organization.id``, both shipped by the auth service. Without
        # auth in the stack the generated migration would FK to non-
        # existent tables and fail at ``alembic upgrade``. Surface that
        # at resolver time instead.
        #
        # If a third option-conditional service dep shows up later,
        # promote this to a generic ``auto_required_services`` field on
        # ``OptionSpec`` (mirrors ``auto_requires`` for components).
        for service in services:
            base_service = extract_base_service_name(service)
            if base_service != AnswerKeys.SERVICE_INSIGHTS:
                continue
            spec = SERVICES.get(base_service)
            if spec is None or not is_spec_with_options(service):
                continue
            try:
                parsed = parse_options(service, spec)
            except ValueError:
                # Parse error already reported above.
                continue
            if parsed.get("per_user"):
                if "auth" not in base_services:
                    errors.append(
                        "Service 'insights[per_user]' requires service 'auth' "
                        "(project rows FK to user.id and organization.id, both "
                        "shipped by auth). Add auth alongside insights."
                    )
                else:
                    # Auth is selected, but per_user FKs to
                    # ``organization.id`` which only ``auth[org]`` ships.
                    # Find the auth selection and verify its level.
                    from .auth_service_parser import parse_auth_service_config

                    for auth_service in services:
                        if (
                            extract_base_service_name(auth_service)
                            != AnswerKeys.SERVICE_AUTH
                        ):
                            continue
                        try:
                            auth_cfg = parse_auth_service_config(auth_service)
                        except ValueError:
                            # Parse error already reported elsewhere.
                            break
                        if auth_cfg.level != AuthLevels.ORG:
                            errors.append(
                                "Service 'insights[per_user]' requires "
                                "'auth[org]'. The per-user variant ships "
                                "migrations that foreign-key to "
                                "organization.id; the org-level auth is what "
                                "creates that table. Found auth level: "
                                f"'{auth_cfg.level}'."
                            )
                        break

        return errors

    @staticmethod
    def get_missing_components_for_services(
        selected_services: list[str], available_components: list[str]
    ) -> list[str]:
        """
        Get components that need to be added for the selected services.

        Args:
            selected_services: List of service names
            available_components: List of already available components

        Returns:
            List of component names that need to be added
        """
        if not selected_services:
            return []

        try:
            resolved_components, _ = ServiceResolver.resolve_service_dependencies(
                selected_services
            )
            missing = set(resolved_components) - set(available_components)
            return sorted(missing)
        except ValueError:
            # If services are invalid, return empty list
            return []

    @staticmethod
    def validate_service_component_compatibility(
        selected_services: list[str], available_components: list[str]
    ) -> list[str]:
        """
        Validate that all required components are available for selected services.

        Args:
            selected_services: List of service names
            available_components: List of available component names

        Returns:
            List of error messages (empty if compatible)
        """
        errors = []

        # First validate the services themselves
        service_errors = ServiceResolver.validate_services(selected_services)
        errors.extend(service_errors)

        # Then check component dependencies
        # Extract base names to handle bracket syntax (e.g., database[postgres] satisfies "database")
        base_available = {extract_base_component_name(c) for c in available_components}
        for service_name in selected_services:
            if service_name not in SERVICES:
                continue  # Already reported in service validation

            service_deps = get_service_dependencies(service_name)
            for required_comp in service_deps:
                if required_comp not in base_available:
                    errors.append(
                        f"Service '{service_name}' requires component '{required_comp}'"
                    )

        return errors

    @staticmethod
    def get_service_component_summary(
        selected_services: list[str],
    ) -> dict[str, list[str]]:
        """
        Get a summary of what components each service requires.

        Args:
            selected_services: List of service names

        Returns:
            Dictionary mapping service names to their required components
        """
        summary = {}

        for service_name in selected_services:
            if service_name in SERVICES:
                summary[service_name] = get_service_dependencies(service_name)
            else:
                summary[service_name] = []  # Unknown service

        return summary

    @staticmethod
    def recommend_components_for_services(selected_services: list[str]) -> list[str]:
        """
        Get recommended (but not required) components for selected services.

        Args:
            selected_services: List of service names

        Returns:
            List of recommended component names
        """
        recommendations = set()

        for service_name in selected_services:
            if service_name not in SERVICES:
                continue

            spec = SERVICES[service_name]
            if spec.recommended_components:
                recommendations.update(spec.recommended_components)

        return sorted(recommendations)

    @staticmethod
    def get_services_requiring_component(component_name: str) -> list[str]:
        """
        Get list of services that require a specific component.

        Args:
            component_name: Name of the component

        Returns:
            List of service names that require this component
        """
        requiring_services = []

        for service_name, spec in SERVICES.items():
            if component_name in spec.required_components:
                requiring_services.append(service_name)

        return requiring_services

    @staticmethod
    def merge_service_and_component_selections(
        selected_services: list[str], selected_components: list[str]
    ) -> tuple[list[str], list[str], list[str]]:
        """
        Merge service and component selections, resolving all dependencies.

        Args:
            selected_services: List of service names
            selected_components: List of component names

        Returns:
            Tuple of (final_components, auto_added_from_services, auto_added_from_components)
            - final_components: Final list of all components
            - auto_added_from_services: Components added due to service requirements
            - auto_added_from_components: Components added due to component dependencies

        Raises:
            ValueError: If services or components are invalid
        """
        # Resolve service dependencies first
        service_components, service_auto_added = (
            ServiceResolver.resolve_service_dependencies(selected_services)
        )

        # Combine with explicitly selected components
        all_components = list(set(selected_components + service_components))

        # Resolve final component dependencies
        final_components = DependencyResolver.resolve_dependencies(all_components)

        # Calculate what was auto-added from component dependencies
        component_auto_added = set(final_components) - set(all_components)

        return (
            final_components,
            sorted(service_auto_added),
            sorted(component_auto_added),
        )
