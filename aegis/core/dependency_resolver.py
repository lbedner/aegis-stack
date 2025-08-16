"""
Component dependency resolution for Aegis Stack.

This module handles dependency resolution, validation, and recommendations
for component selection during project generation.
"""

from .components import COMPONENTS


class DependencyResolver:
    """Handles component dependency resolution and validation."""

    @staticmethod
    def resolve_dependencies(selected_components: list[str]) -> list[str]:
        """
        Resolve all dependencies and return final component list.

        Args:
            selected_components: List of component names selected by user

        Returns:
            Complete list of components including dependencies
        """
        resolved = set(selected_components)

        # Always include core components
        resolved.update(["backend", "frontend"])

        # Resolve hard dependencies recursively
        while True:
            before_size = len(resolved)
            for component_name in list(resolved):
                if component_name not in COMPONENTS:
                    continue

                component = COMPONENTS[component_name]
                if component.requires:
                    resolved.update(component.requires)

            if len(resolved) == before_size:
                break  # No new dependencies added

        return sorted(resolved)

    @staticmethod
    def validate_components(components: list[str]) -> list[str]:
        """
        Validate component selection and return errors.

        Args:
            components: List of component names to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        for component in components:
            if component not in COMPONENTS:
                errors.append(f"Unknown component: {component}")
                continue

            spec = COMPONENTS[component]

            # Check conflicts
            if spec.conflicts:
                for conflict in spec.conflicts:
                    if conflict in components:
                        errors.append(
                            f"Component '{component}' conflicts with '{conflict}'"
                        )

        return errors

    @staticmethod
    def get_recommendations(selected_components: list[str]) -> list[str]:
        """
        Get recommended components based on selection.

        Args:
            selected_components: List of already selected components

        Returns:
            List of recommended component names not already selected
        """
        recommendations = set()

        for component_name in selected_components:
            if component_name not in COMPONENTS:
                continue

            component = COMPONENTS[component_name]
            if component.recommends:
                for rec in component.recommends:
                    if rec not in selected_components:
                        recommendations.add(rec)

        return sorted(recommendations)

    @staticmethod
    def get_missing_dependencies(selected_components: list[str]) -> list[str]:
        """
        Get dependencies that would be auto-added.

        Args:
            selected_components: List of user-selected components

        Returns:
            List of dependencies that would be automatically added
        """
        resolved = DependencyResolver.resolve_dependencies(selected_components)
        core_components = {"backend", "frontend"}
        auto_added = set(resolved) - set(selected_components) - core_components
        return sorted(auto_added)
