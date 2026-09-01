"""
Tests for the ingress component registration.

This module tests that the ingress component is properly registered
in the component system with correct specifications.
"""

from aegis.constants import AnswerKeys, ComponentNames
from aegis.core.components import COMPONENTS, ComponentSpec, ComponentType


class TestIngressComponentRegistry:
    """Test ingress component registration in COMPONENTS dict."""

    def test_ingress_exists_in_registry(self) -> None:
        """Test that ingress component is registered."""
        assert "ingress" in COMPONENTS

    def test_ingress_is_component_spec(self) -> None:
        """Test that ingress is a proper ComponentSpec instance."""
        assert isinstance(COMPONENTS["ingress"], ComponentSpec)

    def test_ingress_name_matches_key(self) -> None:
        """Test that component name matches registry key."""
        spec = COMPONENTS["ingress"]
        assert spec.name == "ingress"

    def test_ingress_type_is_infrastructure(self) -> None:
        """Test that ingress is an infrastructure component."""
        spec = COMPONENTS["ingress"]
        assert spec.type == ComponentType.INFRASTRUCTURE

    def test_ingress_has_description(self) -> None:
        """Test that ingress has a non-empty description."""
        spec = COMPONENTS["ingress"]
        assert spec.description
        assert "Traefik" in spec.description

    def test_ingress_docker_services(self) -> None:
        """Test that ingress has traefik docker service."""
        spec = COMPONENTS["ingress"]
        assert spec.docker_services is not None
        assert "traefik" in spec.docker_services

    def test_ingress_recommends_backend(self) -> None:
        """Test that ingress recommends backend component."""
        spec = COMPONENTS["ingress"]
        assert spec.recommends is not None
        assert "backend" in spec.recommends

    def test_ingress_has_no_hard_requirements(self) -> None:
        """Test that ingress has no hard dependencies."""
        spec = COMPONENTS["ingress"]
        assert spec.requires is not None
        assert len(spec.requires) == 0

    def test_ingress_lists_initialized(self) -> None:
        """Test that all list fields are properly initialized."""
        spec = COMPONENTS["ingress"]
        assert spec.requires is not None
        assert spec.recommends is not None
        assert spec.conflicts is not None
        assert spec.docker_services is not None
        assert spec.pyproject_deps is not None
        assert spec.template_files is not None


class TestIngressInConstants:
    """Test ingress constants in aegis.constants."""

    def test_ingress_in_component_names(self) -> None:
        """Test that INGRESS is defined in ComponentNames."""
        assert hasattr(ComponentNames, "INGRESS")
        assert ComponentNames.INGRESS == "ingress"

    def test_ingress_in_infrastructure_order(self) -> None:
        """Test that ingress is in INFRASTRUCTURE_ORDER."""
        assert ComponentNames.INGRESS in ComponentNames.INFRASTRUCTURE_ORDER

    def test_ingress_is_near_end_of_infrastructure_order(self) -> None:
        """Test that ingress is near the end of the component prompt order.

        Ingress and observability close out the infrastructure questions;
        the htmx frontend trails the whole list, so "near the end" means
        within the last three.
        """
        idx = ComponentNames.INFRASTRUCTURE_ORDER.index(ComponentNames.INGRESS)
        assert idx >= len(ComponentNames.INFRASTRUCTURE_ORDER) - 3

    def test_ingress_in_answer_keys(self) -> None:
        """Test that INGRESS is defined in AnswerKeys."""
        assert hasattr(AnswerKeys, "INGRESS")
        assert AnswerKeys.INGRESS == "include_ingress"

    def test_include_key_generates_correct_value(self) -> None:
        """Test that include_key helper works for ingress."""
        assert AnswerKeys.include_key("ingress") == "include_ingress"


class TestIngressWithOtherComponents:
    """Test ingress component interacts correctly with other components."""

    def test_ingress_in_infrastructure_components(self) -> None:
        """Test that ingress appears in infrastructure component list."""
        from aegis.core.components import ComponentType, get_components_by_type

        infra_components = get_components_by_type(ComponentType.INFRASTRUCTURE)
        assert "ingress" in infra_components

    def test_ingress_in_available_components(self) -> None:
        """Test that ingress appears in available components list."""
        from aegis.core.components import list_available_components

        available = list_available_components()
        assert "ingress" in available

    def test_get_ingress_component(self) -> None:
        """Test that get_component works for ingress."""
        from aegis.core.components import get_component

        spec = get_component("ingress")
        assert spec.name == "ingress"
        assert spec.type == ComponentType.INFRASTRUCTURE

    def test_ingress_dependency_resolution(self) -> None:
        """Test that ingress resolves dependencies correctly."""
        from aegis.core.dependency_resolver import DependencyResolver

        resolver = DependencyResolver()
        resolved = resolver.resolve_dependencies(["ingress"])

        # Ingress has no hard dependencies, so only ingress should be resolved
        assert "ingress" in resolved
        # Recommends (backend) should not be auto-added
        assert len(resolved) == 1

    def test_ingress_with_backend_resolution(self) -> None:
        """Test that ingress with backend resolves correctly."""
        from aegis.core.dependency_resolver import DependencyResolver

        resolver = DependencyResolver()
        resolved = resolver.resolve_dependencies(["ingress", "backend"])

        assert "ingress" in resolved
        assert "backend" in resolved


class TestIngressFileMapping:
    """Test ingress component file mapping in post_gen_tasks."""

    def test_ingress_in_file_mapping(self) -> None:
        """Test that ingress has files in component file mapping."""
        from aegis.core.post_gen_tasks import get_component_file_mapping

        mapping = get_component_file_mapping()
        assert "ingress" in mapping

    def test_ingress_file_mapping_includes_traefik_dir(self) -> None:
        """Test that ingress file mapping includes traefik directory."""
        from aegis.core.post_gen_tasks import get_component_file_mapping

        mapping = get_component_file_mapping()
        assert "traefik" in mapping["ingress"]

    def test_ingress_file_mapping_includes_dashboard_files(self) -> None:
        """Test that ingress file mapping includes dashboard card and modal."""
        from aegis.core.post_gen_tasks import get_component_file_mapping

        mapping = get_component_file_mapping()
        ingress_files = mapping["ingress"]
        assert any("ingress_card.py" in f for f in ingress_files)
        assert any("ingress_modal.py" in f for f in ingress_files)


class TestIngressTemplateFiles:
    """Test that ingress template files exist."""

    def test_traefik_config_template_exists(self) -> None:
        """Test that traefik.yml.jinja template exists."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/traefik/traefik.yml.jinja"
        )
        assert template_path.exists(), f"Template not found: {template_path}"

    def test_traefik_config_has_required_sections(self) -> None:
        """Test that traefik config template has required sections."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/traefik/traefik.yml.jinja"
        )
        content = template_path.read_text()

        # Check for required sections
        assert "api:" in content
        assert "dashboard:" in content
        assert "entryPoints:" in content
        assert "providers:" in content
        assert "docker:" in content

    def test_traefik_config_has_tls_conditionals(self) -> None:
        """Test that traefik config template has TLS conditionals."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/traefik/traefik.yml.jinja"
        )
        content = template_path.read_text()

        # Check for TLS-related conditionals
        assert "ingress_tls" in content
        assert "certificatesResolvers:" in content
        assert "letsencrypt:" in content


class TestDockerComposeIngressService:
    """Test docker-compose.yml.jinja ingress service configuration."""

    def test_docker_compose_has_traefik_service(self) -> None:
        """Test that docker-compose template has traefik service."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/docker-compose.yml.jinja"
        )
        content = template_path.read_text()

        assert "traefik:" in content
        assert "include_ingress" in content

    def test_docker_compose_traefik_image(self) -> None:
        """Test that traefik service uses correct image."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/docker-compose.yml.jinja"
        )
        content = template_path.read_text()

        assert "traefik:v3" in content

    def test_docker_compose_traefik_volumes(self) -> None:
        """Test that traefik service has correct volumes."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/docker-compose.yml.jinja"
        )
        content = template_path.read_text()

        assert "/var/run/docker.sock" in content
        assert "./traefik/traefik.yml" in content

    def test_docker_compose_traefik_healthcheck(self) -> None:
        """Test that traefik service has healthcheck."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/docker-compose.yml.jinja"
        )
        content = template_path.read_text()

        assert "traefik" in content
        assert "healthcheck" in content

    def test_docker_compose_webserver_traefik_labels(self) -> None:
        """Test that webserver has traefik labels when ingress enabled."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/docker-compose.yml.jinja"
        )
        content = template_path.read_text()

        assert "traefik.enable=true" in content
        assert "traefik.http.routers.webserver" in content
        assert "traefik.http.services.webserver" in content

    def test_docker_compose_has_letsencrypt_volume(self) -> None:
        """Test that docker-compose has traefik-letsencrypt volume conditional."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/docker-compose.yml.jinja"
        )
        content = template_path.read_text()

        assert "traefik-letsencrypt:" in content


class TestIngressHealthCheck:
    """Test ingress health check implementation in templates."""

    def test_health_py_has_ingress_check(self) -> None:
        """Test that health.py.jinja has ingress health check function."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/services/system/health.py.jinja"
        )
        content = template_path.read_text()

        assert "check_ingress_health" in content
        assert "include_ingress" in content

    def test_health_check_queries_traefik_api(self) -> None:
        """Test that health check queries Traefik API endpoints."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/services/system/health.py.jinja"
        )
        content = template_path.read_text()

        assert "/api/http/routers" in content
        assert "/api/http/services" in content
        assert "/api/entrypoints" in content

    def test_component_health_registers_ingress(self) -> None:
        """Test that component_health.py.jinja registers ingress check."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/backend/startup/component_health.py.jinja"
        )
        content = template_path.read_text()

        assert "check_ingress_health" in content
        assert 'register_health_check("ingress"' in content


class TestIngressConfig:
    """Test ingress configuration in templates."""

    def test_config_has_traefik_settings(self) -> None:
        """Test that config.py.jinja has Traefik settings."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/core/config.py.jinja"
        )
        content = template_path.read_text()

        assert "TRAEFIK_API_URL" in content
        assert "TRAEFIK_API_URL_LOCAL" in content

    def test_config_has_traefik_effective_property(self) -> None:
        """Test that config has traefik_api_url_effective property."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/core/config.py.jinja"
        )
        content = template_path.read_text()

        assert "traefik_api_url_effective" in content

    def test_env_example_has_traefik_settings(self) -> None:
        """Test that .env.example.jinja has Traefik settings."""
        from pathlib import Path

        template_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/.env.example.jinja"
        )
        content = template_path.read_text()

        assert "TRAEFIK_API_URL" in content
        assert "include_ingress" in content


class TestIngressDashboardCard:
    """Test ingress dashboard card implementation."""

    def test_ingress_card_exists(self) -> None:
        """Test that ingress_card.py exists."""
        from pathlib import Path

        card_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend/dashboard/cards/ingress_card.py"
        )
        assert card_path.exists()

    def test_ingress_card_uses_card_container(self) -> None:
        """Test that ingress card uses CardContainer."""
        from pathlib import Path

        card_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend/dashboard/cards/ingress_card.py"
        )
        content = card_path.read_text()

        assert "CardContainer" in content
        assert "create_header_row" in content
        assert "create_metric_container" in content

    def test_ingress_card_in_init(self) -> None:
        """Test that IngressCard is exported in __init__.py.jinja."""
        from pathlib import Path

        init_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend/dashboard/cards/__init__.py.jinja"
        )
        content = init_path.read_text()

        assert "IngressCard" in content
        assert "ingress_card" in content

    def test_ingress_card_in_main_py(self) -> None:
        """Test that IngressCard is used in main.py.jinja."""
        from pathlib import Path

        main_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend/main.py.jinja"
        )
        content = main_path.read_text()

        assert "IngressCard" in content
        assert 'component_name == "ingress"' in content


class TestIngressModal:
    """Test ingress modal implementation."""

    def test_ingress_modal_exists(self) -> None:
        """Test that ingress_modal.py exists."""
        from pathlib import Path

        modal_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend/dashboard/modals/ingress_modal.py"
        )
        assert modal_path.exists()

    def test_ingress_modal_has_detail_dialog(self) -> None:
        """Test that ingress modal has IngressDetailDialog class."""
        from pathlib import Path

        modal_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend/dashboard/modals/ingress_modal.py"
        )
        content = modal_path.read_text()

        assert "class IngressDetailDialog" in content
        assert "BaseDetailPopup" in content

    def test_ingress_modal_has_overview_section(self) -> None:
        """Test that ingress modal has OverviewSection."""
        from pathlib import Path

        modal_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend/dashboard/modals/ingress_modal.py"
        )
        content = modal_path.read_text()

        assert "class OverviewSection" in content
        assert "MetricCard" in content

    def test_ingress_modal_has_routers_section(self) -> None:
        """Test that ingress modal has RoutersSection."""
        from pathlib import Path

        modal_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend/dashboard/modals/ingress_modal.py"
        )
        content = modal_path.read_text()

        assert "class RoutersSection" in content
        assert "class RouterRow" in content

    def test_ingress_modal_in_init(self) -> None:
        """Test that IngressDetailDialog is exported in __init__.py.jinja."""
        from pathlib import Path

        init_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend/dashboard/modals/__init__.py.jinja"
        )
        content = init_path.read_text()

        assert "IngressDetailDialog" in content
        assert "ingress_modal" in content

    def test_ingress_modal_in_registry(self) -> None:
        """Test that IngressDetailDialog is registered in modal_registry.py.jinja."""
        from pathlib import Path

        registry_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend/dashboard/modal_registry.py.jinja"
        )
        content = registry_path.read_text()

        assert "IngressDetailDialog" in content
        assert '"ingress": IngressDetailDialog' in content


class TestIngressDiagramLayout:
    """Test ingress in diagram layout."""

    def test_ingress_in_radial_positions(self) -> None:
        """Test that ingress has a radial position defined."""
        from pathlib import Path

        layout_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend/dashboard/diagram/layout.py"
        )
        content = layout_path.read_text()

        assert '"ingress"' in content
        assert "RADIAL_POSITIONS" in content

    def test_ingress_connection_to_backend(self) -> None:
        """Test that ingress connects to backend in diagram."""
        from pathlib import Path

        layout_path = Path(
            "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend/dashboard/diagram/layout.py"
        )
        content = layout_path.read_text()

        assert '"ingress"' in content
        assert "ingress" in content and "backend" in content
