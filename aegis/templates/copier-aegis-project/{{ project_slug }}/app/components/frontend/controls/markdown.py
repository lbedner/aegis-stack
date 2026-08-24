"""The house markdown treatment, shared by every surface that renders it.

One style sheet definition so agent notes, chat bubbles, exception
stacktraces, and future markdown surfaces cannot drift apart
typographically - the code-block treatment (mono font, surface-container
background, highlight theme) previously lived as three separate copies in
the observability, database and blog modals.
"""

import re

import flet as ft

from app.components.frontend.controls.text import SecondaryText
from app.components.frontend.theme import AegisTheme as Theme

# Cheap structural sniff: only pay the Markdown control's layout cost when
# the body actually uses markdown syntax.
MARKDOWN_RE = re.compile(r"(^#{1,6}\s|\*\*|__|^[-*]\s|`|\[.+\]\(.+\))", re.MULTILINE)


def code_highlight_theme(dark: bool = True) -> str:
    """The syntax-highlight theme name for the current mode."""
    return "ir-black" if dark else "atom-one-light"


def markdown_style_sheet(color: str | None = None) -> ft.MarkdownStyleSheet:
    """Body text styled like the rest of the app, not the widget default.

    Defaults to the muted secondary tone (agent notes); pass
    ``Theme.Colors.TEXT_PRIMARY`` for main-content bodies like chat.
    Code spans and blocks get the house treatment (mono font on a
    surface-container background) instead of the widget's unthemed
    light-blue default.
    """
    body_style = ft.TextStyle(
        font_family="Roboto",
        size=Theme.Typography.BODY,
        color=color or Theme.Colors.TEXT_SECONDARY,
    )
    code_style = ft.TextStyle(
        size=12,
        font_family="Roboto Mono",
        weight=ft.FontWeight.W_400,
        height=1.2,
    )
    block_decoration = ft.BoxDecoration(
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border_radius=ft.border_radius.all(8),
    )
    return ft.MarkdownStyleSheet(
        p_text_style=body_style,
        list_bullet_text_style=body_style,
        code_text_style=code_style,
        codeblock_decoration=block_decoration,
        blockquote_decoration=block_decoration,
    )


def markdown_control(
    value: str = "",
    *,
    selectable: bool = True,
    color: str | None = None,
    dark: bool = True,
) -> ft.Markdown:
    """A themed markdown control for bodies that mutate (e.g. streaming)."""
    return ft.Markdown(
        value=value,
        selectable=selectable,
        extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
        code_theme=code_highlight_theme(dark),
        md_style_sheet=markdown_style_sheet(color),
    )


def markdown_or_text(body: str) -> ft.Control:
    """Render markdown when the body uses it, plain SecondaryText when not."""
    if not MARKDOWN_RE.search(body):
        return SecondaryText(body)
    return markdown_control(body)
