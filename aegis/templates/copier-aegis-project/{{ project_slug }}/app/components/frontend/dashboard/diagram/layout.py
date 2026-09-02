"""
Layout calculations for diagram visualization.

Provides positioning algorithms for tree and radial layouts.
"""

from dataclasses import dataclass
from enum import Enum

from app.services.system.models import ComponentStatus


class LayoutType(Enum):
    """Supported diagram layout types."""

    TREE = "tree"
    RADIAL = "radial"


@dataclass
class NodePosition:
    """Position data for a diagram node."""

    x: float  # Normalized X position (-1 to 1)
    y: float  # Normalized Y position (-1 to 1)
    component_name: str
    component_data: ComponentStatus


# Manual radial positions for optimal visual layout
# Coordinates are normalized (-1 to 1), centered at (0, 0)
# These positions are hand-tuned: compact layout
# Ingress → Server hierarchy at top, other components radiate from Server
RADIAL_POSITIONS: dict[str, tuple[float, float]] = {
    "ingress": (0.0, -0.45),  # Top center - entry point
    "backend": (0.0, -0.10),  # Below ingress - the hub
    "worker": (-0.45, -0.35),  # Upper-left
    "scheduler": (0.45, -0.35),  # Upper-right
    "database": (-0.50, 0.0),  # Left
    "ollama": (0.50, 0.0),  # Right
    "cache": (-0.15, 0.30),  # Bottom-center-left
    "storage": (-0.50, -0.25),  # Left, above database
    "service_auth": (0.15, 0.30),  # Bottom-center-right
    "service_ai": (0.50, 0.25),  # Bottom-right
    "service_comms": (-0.50, 0.25),  # Bottom-left
}


def get_connections(components: dict[str, ComponentStatus]) -> list[tuple[str, str]]:
    """
    Get connection pairs between components.

    Backend (Server) is the central hub connecting to all components.
    Ingress sits in front of backend as the entry point.
    Additional connections show component relationships.

    Args:
        components: Dictionary of component names to their status

    Returns:
        List of (parent, child) connection tuples
    """
    connections: list[tuple[str, str]] = []

    # Ingress → Backend (if ingress exists)
    if "ingress" in components and "backend" in components:
        connections.append(("ingress", "backend"))

    # All components connect through backend (except ingress which connects TO backend)
    for name in components:
        if name != "backend" and name != "ingress":
            connections.append(("backend", name))

    # Inference → AI Service
    if "ollama" in components and "service_ai" in components:
        connections.append(("ollama", "service_ai"))

    return connections


def calculate_tree_positions(
    components: dict[str, ComponentStatus],
) -> list[NodePosition]:
    """
    Calculate tree layout positions with ingress at top, backend below.

    Arranges components in a 4-tier hierarchical tree structure:
    - Ingress (Traefik) at top center - entry point
    - Backend (Server) below ingress
    - Infrastructure components in third row
      (database, cache, worker, scheduler, ollama)
    - Services in bottom row

    Args:
        components: Dictionary of component names to their status

    Returns:
        List of NodePosition objects with normalized coordinates
    """
    positions: list[NodePosition] = []

    # Separate into categories
    ingress_data = components.get("ingress")
    backend_data = components.get("backend")

    # Infrastructure components (excludes backend and ingress)
    infra_names = [
        name
        for name in components
        if name not in ("backend", "ingress") and not name.startswith("service_")
    ]

    # Services at bottom
    service_names = [name for name in components if name.startswith("service_")]

    # Tier 0: Ingress at very top (if present)
    if ingress_data:
        positions.append(
            NodePosition(
                x=0.0, y=-0.48, component_name="ingress", component_data=ingress_data
            )
        )

    # Tier 1: Backend below ingress
    if backend_data:
        backend_y = -0.40 if not ingress_data else -0.30
        positions.append(
            NodePosition(
                x=0.0,
                y=backend_y,
                component_name="backend",
                component_data=backend_data,
            )
        )

    # Tier 2: Infrastructure components
    if infra_names:
        count = len(infra_names)
        spacing = 1.3 / max(count - 1, 1) if count > 1 else 0
        start_x = -1.3 / 2 if count > 1 else 0.0

        for i, name in enumerate(sorted(infra_names)):
            x = start_x + (i * spacing) if count > 1 else 0.0
            positions.append(
                NodePosition(
                    x=x,
                    y=-0.05,
                    component_name=name,
                    component_data=components[name],
                )
            )

    # Tier 3: Services in bottom row
    if service_names:
        count = len(service_names)
        spacing = 1.1 / max(count - 1, 1) if count > 1 else 0
        start_x = -1.1 / 2 if count > 1 else 0.0

        for i, name in enumerate(sorted(service_names)):
            x = start_x + (i * spacing) if count > 1 else 0.0
            positions.append(
                NodePosition(
                    x=x,
                    y=0.25,
                    component_name=name,
                    component_data=components[name],
                )
            )

    return positions


def calculate_radial_positions(
    components: dict[str, ComponentStatus],
) -> list[NodePosition]:
    """
    Calculate radial layout positions using manual coordinates.

    Uses hand-tuned positions from RADIAL_POSITIONS dict for optimal
    visual layout. Falls back to algorithmic placement for unknown components.

    Args:
        components: Dictionary of component names to their status

    Returns:
        List of NodePosition objects with normalized coordinates
    """
    positions: list[NodePosition] = []

    for name, data in components.items():
        if name in RADIAL_POSITIONS:
            x, y = RADIAL_POSITIONS[name]
        else:
            # Fallback for unknown components - place in outer ring
            import math

            unknown_names = [n for n in components if n not in RADIAL_POSITIONS]
            index = unknown_names.index(name) if name in unknown_names else 0
            count = len(unknown_names)
            angle = (2 * math.pi * index / max(count, 1)) - (math.pi / 2)
            x = 0.6 * math.cos(angle)
            y = 0.6 * math.sin(angle)

        positions.append(
            NodePosition(x=x, y=y, component_name=name, component_data=data)
        )

    return positions


def calculate_positions(
    components: dict[str, ComponentStatus],
    layout_type: LayoutType,
) -> list[NodePosition]:
    """
    Calculate node positions for the specified layout type.

    Args:
        components: Dictionary of component names to their status
        layout_type: The layout algorithm to use

    Returns:
        List of NodePosition objects with normalized coordinates
    """
    if layout_type == LayoutType.TREE:
        return calculate_tree_positions(components)
    else:
        return calculate_radial_positions(components)
