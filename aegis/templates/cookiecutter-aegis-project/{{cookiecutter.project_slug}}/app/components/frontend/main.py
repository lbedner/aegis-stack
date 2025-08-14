import asyncio
from collections.abc import Awaitable, Callable

import flet as ft

from app.services.system import get_system_status
from app.services.system.models import ComponentStatus


def create_frontend_app() -> Callable[[ft.Page], Awaitable[None]]:
    """Returns the Flet target function - system health dashboard"""

    async def flet_main(page: ft.Page) -> None:
        page.title = "{{ cookiecutter.project_name }} - System Dashboard"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.padding = 20
        page.scroll = ft.ScrollMode.AUTO

        # Dashboard header
        header = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "{{ cookiecutter.project_name }}",
                        size=32,
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Text(
                        "System Health Dashboard", size=18, color=ft.Colors.GREY_600
                    ),
                ]
            ),
            margin=ft.margin.only(bottom=20),
        )

        # System status container
        status_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Loading system status...", size=16),
                ]
            ),
            padding=20,
            border=ft.border.all(2, ft.Colors.GREY_300),
            border_radius=8,
        )

        # Component details container
        components_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Component Status", size=20, weight=ft.FontWeight.BOLD),
                    ft.Text("Loading components...", size=14),
                ]
            ),
            padding=20,
            margin=ft.margin.only(top=20),
            border=ft.border.all(2, ft.Colors.GREY_300),
            border_radius=8,
        )

        # System info container
        system_info_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text("System Information", size=20, weight=ft.FontWeight.BOLD),
                    ft.Text("Loading system info...", size=14),
                ]
            ),
            padding=20,
            margin=ft.margin.only(top=20),
            border=ft.border.all(2, ft.Colors.GREY_300),
            border_radius=8,
        )

        # Add components to page
        page.add(
            header,
            status_container,
            components_container,
            system_info_container,
        )

        async def refresh_status() -> None:
            """Refresh system status data"""
            try:
                status = await get_system_status()

                # Update overall status
                status_color = (
                    ft.Colors.GREEN if status.overall_healthy else ft.Colors.RED
                )
                status_icon = "✅" if status.overall_healthy else "❌"
                status_text = "Healthy" if status.overall_healthy else "Issues Detected"

                healthy_str = (
                    f"Components: {len(status.healthy_top_level_components)}/"
                    f"{status.total_components} healthy"
                )
                status_container.content = ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(status_icon, size=24),
                                ft.Text(
                                    f"System Status: {status_text}",
                                    size=20,
                                    weight=ft.FontWeight.BOLD,
                                    color=status_color,
                                ),
                            ]
                        ),
                        ft.Text(f"Health: {status.health_percentage:.1f}%", size=16),
                        ft.Text(
                            healthy_str,
                            size=14,
                        ),
                        ft.Text(
                            f"Last Updated: {status.timestamp.strftime('%H:%M:%S')}",
                            size=12,
                            color=ft.Colors.GREY_600,
                        ),
                    ]
                )

                # Update system info
                system_info_content = [
                    ft.Text("System Information", size=20, weight=ft.FontWeight.BOLD)
                ]
                if status.system_info:
                    for key, value in status.system_info.items():
                        system_info_content.append(
                            ft.Row(
                                [
                                    ft.Text(
                                        f"{key.replace('_', ' ').title()}:",
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Text(str(value)),
                                ]
                            )
                        )
                else:
                    system_info_content.append(
                        ft.Text("No system information available.")
                    )
                system_info_container.content = ft.Column(system_info_content)

                # Organize components by hierarchy
                core_components = {
                    k: v
                    for k, v in status.components.items()
                    if k in ["backend", "frontend"]
                }
                optional_components = {
                    k: v
                    for k, v in status.components.items()
                    if k not in ["backend", "frontend"]
                }

                def create_sub_component_card(
                    name: str, component: ComponentStatus
                ) -> ft.Container:
                    """Create a smaller card for sub-components."""
                    color = ft.Colors.GREEN if component.healthy else ft.Colors.RED
                    icon = "✅" if component.healthy else "❌"
                    return ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text(icon, size=12),
                                        ft.Text(
                                            name.title(),
                                            size=12,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                    ]
                                ),
                                ft.Text(component.message, size=10),
                            ]
                        ),
                        padding=8,
                        border=ft.border.all(1, color),
                        border_radius=4,
                        width=150,
                    )

                def create_component_card(
                    name: str, component: ComponentStatus, tier: str
                ) -> ft.Container:
                    """Create a styled component card based on tier."""
                    color = ft.Colors.GREEN if component.healthy else ft.Colors.RED
                    icon = "✅" if component.healthy else "❌"

                    # Tier-specific styling
                    if tier == "core":
                        card_width = 480
                        border_width = 2
                        name_size = 18
                        tier_indicator = ft.Container(
                            content=ft.Text(
                                "CORE",
                                size=8,
                                color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD,
                            ),
                            bgcolor=ft.Colors.BLUE_600,
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                            border_radius=3,
                        )
                    else:  # optional
                        card_width = 220
                        border_width = 1
                        name_size = 16
                        tier_indicator = ft.Container(
                            content=ft.Text(
                                "OPTIONAL",
                                size=8,
                                color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD,
                            ),
                            bgcolor=ft.Colors.PURPLE_600,
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                            border_radius=3,
                        )

                    # Build component card content
                    card_content = [
                        ft.Row(
                            [
                                ft.Text(icon, size=16),
                                ft.Text(
                                    name.title(),
                                    size=name_size,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                tier_indicator,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(component.message, size=11),
                    ]

                    # Add sub-components if they exist
                    if component.sub_components:
                        sub_cards = [
                            create_sub_component_card(sub_name, sub_comp)
                            for sub_name, sub_comp in component.sub_components.items()
                        ]
                        card_content.append(ft.Container(height=10))
                        card_content.append(ft.Row(sub_cards, wrap=True, spacing=5))

                    return ft.Container(
                        content=ft.Column(card_content),
                        padding=12,
                        margin=5,
                        border=ft.border.all(border_width, color),
                        border_radius=5,
                        width=card_width,
                    )

                # Build component sections
                sections = []

                if core_components:
                    core_cards = [
                        create_component_card(name, comp, "core")
                        for name, comp in core_components.items()
                    ]
                    sections.append(
                        ft.Column(
                            [
                                ft.Text(
                                    "🏗️ Core Components",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.BLUE_700,
                                ),
                                ft.Row(core_cards, wrap=True, spacing=10),
                            ]
                        )
                    )

                if optional_components:
                    optional_cards = [
                        create_component_card(name, comp, "optional")
                        for name, comp in optional_components.items()
                    ]
                    sections.append(
                        ft.Column(
                            [
                                ft.Text(
                                    "🧩 Optional Components",
                                    size=16,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.PURPLE_700,
                                ),
                                ft.Row(optional_cards, wrap=True, spacing=10),
                            ]
                        )
                    )

                final_content = [
                    ft.Text("Component Status", size=20, weight=ft.FontWeight.BOLD)
                ]
                for i, section in enumerate(sections):
                    if i > 0:
                        final_content.append(ft.Container(height=20))
                    final_content.append(section)

                if sections:
                    components_container.content = ft.Column(final_content)
                else:
                    components_container.content = ft.Column(
                        [
                            ft.Text(
                                "Component Status",
                                size=20,
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Text("No components found", size=14),
                        ]
                    )

                page.update()

            except Exception as e:
                status_container.content = ft.Column(
                    [
                        ft.Text(
                            "❌ Error loading system status",
                            size=18,
                            color=ft.Colors.RED,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(str(e), size=12, color=ft.Colors.GREY_600),
                    ]
                )
                page.update()

        async def auto_refresh() -> None:
            while True:
                await refresh_status()
                await asyncio.sleep(30)

        await refresh_status()
        asyncio.create_task(auto_refresh())

    return flet_main