"""
Template generation and context building for Aegis Stack projects.

This module handles the generation of cookiecutter context and manages
the template rendering process based on selected components.
"""

from typing import Any

from .components import COMPONENTS


class TemplateGenerator:
    """Handles template context generation for cookiecutter."""

    def __init__(self, project_name: str, selected_components: list[str]):
        """
        Initialize template generator.

        Args:
            project_name: Name of the project being generated
            selected_components: List of component names to include
        """
        self.project_name = project_name
        self.project_slug = project_name.lower().replace(" ", "-").replace("_", "-")
        self.components = selected_components
        self.component_specs = {
            name: COMPONENTS[name] for name in selected_components if name in COMPONENTS
        }

    def get_template_context(self) -> dict[str, Any]:
        """
        Generate cookiecutter context from components.

        Returns:
            Dictionary containing all template variables
        """
        return {
            "project_name": self.project_name,
            "project_slug": self.project_slug,
            # Component flags for template conditionals - cookiecutter needs yes/no
            "include_redis": "yes" if "redis" in self.components else "no",
            "include_worker": "yes" if "worker" in self.components else "no",
            "include_scheduler": "yes" if "scheduler" in self.components else "no",
            # Derived flags for template logic
            "has_background_infrastructure": any(
                name in self.components for name in ["worker", "scheduler"]
            ),
            "needs_redis": "redis" in self.components,
            # Dependency lists for templates
            "selected_components": self.components,
            "docker_services": self._get_docker_services(),
            "pyproject_dependencies": self._get_pyproject_deps(),
        }

    def _get_docker_services(self) -> list[str]:
        """
        Collect all docker services needed.

        Returns:
            List of docker service names
        """
        services = []
        for component_name in self.components:
            if component_name in self.component_specs:
                spec = self.component_specs[component_name]
                if spec.docker_services:
                    services.extend(spec.docker_services)
        return list(dict.fromkeys(services))  # Preserve order, remove duplicates

    def _get_pyproject_deps(self) -> list[str]:
        """
        Collect all Python dependencies.

        Returns:
            Sorted list of Python package dependencies
        """
        deps = []
        for component_name in self.components:
            if component_name in self.component_specs:
                spec = self.component_specs[component_name]
                if spec.pyproject_deps:
                    deps.extend(spec.pyproject_deps)
        return sorted(set(deps))  # Sort and deduplicate

    def get_template_files(self) -> list[str]:
        """
        Get list of template files that should be included.

        Returns:
            List of template file paths
        """
        files = []
        for component_name in self.components:
            if component_name in self.component_specs:
                spec = self.component_specs[component_name]
                if spec.template_files:
                    files.extend(spec.template_files)
        return list(dict.fromkeys(files))  # Preserve order, remove duplicates
