"""
System domain Pydantic models.

Type-safe data models for system health monitoring, alerts, and status reporting.
All models provide runtime validation and automatic FastAPI integration.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ComponentStatus(BaseModel):
    """Status of a single system component."""

    name: str = Field(..., description="Component name")
    healthy: bool = Field(..., description="Whether component is healthy")
    message: str = Field(..., description="Status message or error description")
    response_time_ms: float | None = Field(
        None, description="Response time in milliseconds"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional component metadata"
    )
    sub_components: dict[str, "ComponentStatus"] = Field(
        default_factory=dict, 
        description="Sub-components (e.g., system metrics under backend)"
    )


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
            all_components.append((name, component))
            # Add sub-components with parent.child naming
            for sub_name, sub_component in component.sub_components.items():
                all_components.append((f"{name}.{sub_name}", sub_component))
        return all_components

    @property
    def healthy_components(self) -> list[str]:
        """List of healthy component names (including sub-components)."""
        return [
            name for name, component in self._get_all_components_flat() 
            if component.healthy
        ]

    @property
    def unhealthy_components(self) -> list[str]:
        """List of unhealthy component names (including sub-components)."""
        return [
            name for name, component in self._get_all_components_flat() 
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


# Singleton for alert severity constants
alert_severity = AlertSeverity()
