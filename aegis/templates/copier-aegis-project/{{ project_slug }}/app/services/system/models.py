"""
System domain Pydantic models.

Type-safe data models for system health monitoring, alerts, and status reporting.
All models provide runtime validation and automatic FastAPI integration.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class ComponentStatusType(str, Enum):
    """Component status levels."""

    HEALTHY = "healthy"
    INFO = "info"
    WARNING = "warning"
    UNHEALTHY = "unhealthy"


class ComponentStatus(BaseModel):
    """Status of a single system component."""

    name: str = Field(..., description="Component name")
    status: ComponentStatusType = Field(
        default=ComponentStatusType.HEALTHY,
        description="Detailed status level (healthy/info/warning/unhealthy)",
    )
    message: str = Field(..., description="Status message or error description")
    response_time_ms: float | None = Field(
        None, description="Response time in milliseconds"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional component metadata"
    )
    sub_components: dict[str, "ComponentStatus"] = Field(
        default_factory=dict,
        description="Sub-components (e.g., system metrics under backend)",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def healthy(self) -> bool:
        """
        Component is healthy only if status is HEALTHY.

        INFO, WARNING, and UNHEALTHY are not considered healthy for counting.
        """
        return self.status == ComponentStatusType.HEALTHY


class SystemStatus(BaseModel):
    """Overall system status with component details."""

    components: dict[str, ComponentStatus] = Field(
        ..., description="Component status by name"
    )
    overall_healthy: bool = Field(..., description="Whether all components are healthy")
    timestamp: datetime = Field(..., description="When status was generated")
    system_info: dict[str, Any] = Field(
        default_factory=dict, description="System information"
    )

    def _get_all_components_flat(self) -> list[tuple[str, ComponentStatus]]:
        """Get all components including sub-components as a flat list."""
        all_components = []

        for name, component in self.components.items():
            all_components.extend(self._flatten_component(name, component))

        return all_components

    def _flatten_component(
        self, name: str, component: ComponentStatus
    ) -> list[tuple[str, ComponentStatus]]:
        """Recursively flatten a component and its sub-components into a list."""
        result = [(name, component)]
        # Recursively add sub-components with parent.child naming
        for sub_name, sub_component in component.sub_components.items():
            result.extend(self._flatten_component(f"{name}.{sub_name}", sub_component))
        return result

    @property
    def healthy_components(self) -> list[str]:
        """List of healthy component names (including sub-components)."""
        return [
            name
            for name, component in self._get_all_components_flat()
            if component.healthy
        ]

    @property
    def unhealthy_components(self) -> list[str]:
        """List of unhealthy component names (including sub-components)."""
        return [
            name
            for name, component in self._get_all_components_flat()
            if not component.healthy
        ]

    @property
    def health_percentage(self) -> float:
        """Percentage of healthy components (including sub-components)."""
        all_components = self._get_all_components_flat()
        if not all_components:
            return 100.0
        healthy_count = len([c for _, c in all_components if c.healthy])
        return (healthy_count / len(all_components)) * 100

    @property
    def total_components(self) -> int:
        """Total number of top-level components."""
        return len(self.components)

    @property
    def healthy_top_level_components(self) -> list[str]:
        """List of healthy top-level component names."""
        return [name for name, comp in self.components.items() if comp.healthy]

    @property
    def services_status(self) -> ComponentStatus | None:
        """Get the services component status if it exists."""
        if "aegis" in self.components:
            aegis_component = self.components["aegis"]
            if (
                hasattr(aegis_component, "sub_components")
                and aegis_component.sub_components
            ):
                return aegis_component.sub_components.get("services")
        return None

    @property
    def has_services(self) -> bool:
        """Check if any services are registered in the system."""
        return self.services_status is not None

    @property
    def service_names(self) -> list[str]:
        """Get list of registered service names."""
        services_component = self.services_status
        if services_component and hasattr(services_component, "sub_components"):
            return list(services_component.sub_components.keys())
        return []

    @property
    def healthy_services(self) -> list[str]:
        """List of healthy service names."""
        services_component = self.services_status
        if services_component and hasattr(services_component, "sub_components"):
            return [
                name
                for name, service in services_component.sub_components.items()
                if service.healthy
            ]
        return []

    @property
    def unhealthy_services(self) -> list[str]:
        """List of unhealthy service names."""
        services_component = self.services_status
        if services_component and hasattr(services_component, "sub_components"):
            return [
                name
                for name, service in services_component.sub_components.items()
                if not service.healthy
            ]
        return []


class HealthResponse(BaseModel):
    """Basic health check API response."""

    healthy: bool = Field(..., description="Whether system is healthy")
    status: str = Field(..., description="Overall status text")
    components: dict[str, ComponentStatus] = Field(
        default_factory=dict, description="Component statuses"
    )
    timestamp: str = Field(..., description="ISO timestamp when checked")


class DetailedHealthResponse(BaseModel):
    """Detailed health check API response with system information."""

    healthy: bool = Field(..., description="Whether system is healthy")
    status: str = Field(..., description="Overall status text")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    components: dict[str, ComponentStatus] = Field(
        ..., description="Component statuses"
    )
    system_info: dict[str, Any] = Field(..., description="System information")
    timestamp: str = Field(..., description="ISO timestamp when checked")
    healthy_components: list[str] = Field(
        ..., description="List of healthy component names"
    )
    unhealthy_components: list[str] = Field(
        ..., description="List of unhealthy component names"
    )
    health_percentage: float = Field(
        ..., description="Percentage of healthy components"
    )
    # Service-specific fields (optional)
    has_services: bool = Field(
        default=False, description="Whether any services are registered"
    )
    service_names: list[str] = Field(
        default_factory=list, description="List of registered service names"
    )
    healthy_services: list[str] = Field(
        default_factory=list, description="List of healthy service names"
    )
    unhealthy_services: list[str] = Field(
        default_factory=list, description="List of unhealthy service names"
    )


class AlertSeverity(BaseModel):
    """Alert severity levels as constants."""

    INFO: str = Field(default="info", description="Informational alert")
    WARNING: str = Field(default="warning", description="Warning alert")
    ERROR: str = Field(default="error", description="Error alert")
    CRITICAL: str = Field(default="critical", description="Critical alert")


class Alert(BaseModel):
    """System alert model."""

    severity: str = Field(..., description="Alert severity level")
    title: str = Field(..., min_length=1, description="Alert title")
    message: str = Field(..., min_length=1, description="Alert message")
    timestamp: datetime = Field(..., description="When alert was created")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional alert data"
    )


class MigrationInfo(BaseModel):
    """Migration file metadata for dashboard display."""

    revision: str
    down_revision: str | None = None
    description: str = "No description"
    content: str = ""
    file_mtime: float = 0.0
    create_date: str | None = None
    file_path: str = ""
    is_current: bool = False


# Singleton for alert severity constants
alert_severity = AlertSeverity()


class LoadReading(BaseModel):
    """A fresh Python's memory in use, in bytes, before and after it loaded
    one part of the app (``load_cost``)."""

    before: int
    after: int


class LoadCosts(BaseModel):
    """What the app's core and each part of it cost the webserver to load,
    in bytes (``load_cost``): each part loaded alone on top of the core,
    keyed as the name registry keys it."""

    core: int = Field(0, description="Python and the app's core")
    parts: dict[str, int] = Field(default_factory=dict)
