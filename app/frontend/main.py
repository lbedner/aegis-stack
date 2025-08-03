from collections.abc import Awaitable, Callable

import flet as ft


def create_frontend_app() -> Callable[[ft.Page], Awaitable[None]]:
    """Returns the Flet target function - pure frontend logic"""

    async def flet_main(page: ft.Page) -> None:
        page.title = "Aegis Stack"
        page.add(ft.Text("Hello Aegis Stack!", size=30))
        page.update()

    return flet_main
