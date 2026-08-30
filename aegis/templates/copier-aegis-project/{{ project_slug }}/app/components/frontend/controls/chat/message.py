"""One chat message bubble: role header, markdown body, quiet footer."""

from typing import Any

import flet as ft

from app.components.frontend.controls.busy_bar import busy_bar
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.markdown import markdown_control
from app.components.frontend.controls.text import LabelText, SecondaryText
from app.components.frontend.theme import AegisTheme as Theme

from .stream import footer_line, trace_failed, trace_label, trace_output

# Long messages wrap well before the far edge; short ones hug their side.
_ALIGN_INSET = 96


class ChatMessageBubble(ft.Container):
    """A single message in the transcript.

    User messages sit on an accent-tinted card pinned to the right, sized
    to their content. Assistant messages render borderless on the page
    background and show the house busy bar until the first token lands.
    """

    def __init__(
        self,
        *,
        role: str,
        text: str = "",
        agent_name: str = "Assistant",
        tool_trace: list[dict[str, Any]] | None = None,
    ):
        super().__init__()
        self.role = role
        is_user = role == "user"

        self._body = markdown_control(text, color=Theme.Colors.TEXT_PRIMARY)
        self._footer = SecondaryText(
            "", size=Theme.Typography.BODY_SMALL, visible=False
        )
        self._trail = ft.Column([], spacing=2, tight=True, visible=False)
        # In-conversation components (approval cards, future previews):
        # system-rendered from typed tool-result data, never model layout.
        self._components = ft.Column(
            [],
            spacing=Theme.Spacing.SM,
            tight=True,
            visible=False,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._waiting = ft.Container(
            content=busy_bar(width=160),
            padding=ft.padding.symmetric(vertical=Theme.Spacing.XS),
            visible=False,
        )
        if tool_trace:
            self.set_tool_trace(tool_trace)

        self.content = ft.Column(
            [
                LabelText("You" if is_user else agent_name),
                self._trail,
                self._body,
                self._components,
                self._waiting,
                self._footer,
            ],
            spacing=Theme.Spacing.XS,
            tight=True,
        )
        self.padding = Theme.Spacing.MD
        if is_user:
            self.border_radius = Theme.Components.CARD_RADIUS
            self.bgcolor = ft.Colors.with_opacity(0.15, Theme.Colors.ACCENT)

    def in_row(self) -> ft.Control:
        """The transcript row for this bubble: user messages pin right and
        size to content; assistant messages sit flush left, transparent."""
        if self.role == "user":
            return ft.Container(
                content=self,
                alignment=ft.alignment.center_right,
                padding=ft.padding.only(left=_ALIGN_INSET),
            )
        return ft.Container(content=self, padding=ft.padding.only(right=_ALIGN_INSET))

    # -- waiting indicator -------------------------------------------------

    def start_thinking(self) -> None:
        """Show the house busy bar until the first token arrives."""
        if self.role == "user":
            return
        self._waiting.visible = True
        if self._waiting.page:
            self._waiting.update()

    def add_tool_call(self, label: str) -> None:
        """Append one call to the visible trail and bring the busy bar
        back; the body has been reset (pre-tool narration is dropped).
        The trail persists after the answer lands."""
        if self.role == "user":
            return
        self._trail.controls.append(
            SecondaryText(label, size=Theme.Typography.BODY_SMALL)
        )
        self._trail.visible = True
        self._body.value = ""
        self._waiting.visible = True
        if self.page:
            self.update()

    def _stop_thinking(self) -> None:
        if not self._waiting.visible:
            return
        self._waiting.visible = False
        if self._waiting.page:
            self._waiting.update()

    # -- expandable tool trace ---------------------------------------------

    def set_tool_trace(self, trace: list[dict[str, Any]]) -> None:
        """Rebuild the trail from the persisted trace: one clickable line
        per call, expanding to the full script and its output."""
        self._trail.controls = [self._trace_row(entry) for entry in trace]
        self._trail.visible = bool(trace)
        if self.page:
            self._trail.update()

    def _trace_row(self, entry: dict[str, Any]) -> ft.Control:
        failed = trace_failed(entry)
        label = SecondaryText(
            trace_label(entry),
            size=Theme.Typography.BODY_SMALL,
            no_wrap=True,
            selectable=False,
        )
        if failed:
            label.color = Theme.Colors.ERROR
        return ft.Container(
            content=label,
            border_radius=Theme.Components.BUTTON_RADIUS,
            padding=ft.padding.symmetric(horizontal=Theme.Spacing.XS, vertical=1),
            ink=True,
            tooltip="Expand this failed run" if failed else "Expand this run",
            on_click=lambda _event, e=entry: self._open_trace_dialog(e),
        )

    def _open_trace_dialog(self, entry: dict[str, Any]) -> None:
        sections: list[ft.Control] = []
        code = entry.get("code")
        if isinstance(code, str) and code:
            sections.append(LabelText("Script"))
            sections.append(markdown_control(f"```python\n{code}\n```"))
        args = entry.get("args")
        if args and not code:
            sections.append(LabelText("Arguments"))
            sections.append(markdown_control(f"```json\n{args}\n```"))
        output = trace_output(entry)
        if output:
            sections.append(LabelText("Output"))
            sections.append(markdown_control(f"```\n{output}\n```"))
        for nested in entry.get("nested") or []:
            sections.append(
                SecondaryText(
                    f"dispatched {nested.get('tool')}({nested.get('args', '')})",
                    size=Theme.Typography.BODY_SMALL,
                )
            )
        if not sections:
            sections = [SecondaryText("No detail recorded for this call.")]

        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
                self.page.update()

        dialog = StyledAlertDialog(
            title=str(entry.get("tool", "tool call")),
            body=ft.Container(
                content=ft.Column(
                    sections,
                    tight=True,
                    spacing=Theme.Spacing.SM,
                    scroll=ft.ScrollMode.AUTO,
                ),
                height=420,
            ),
            width=640,
            on_close=_close,
        )
        self.page.open(dialog)

    # -- streaming ---------------------------------------------------------

    def set_streaming_text(self, text: str) -> None:
        """Replace the body with an in-flight snapshot (already balanced)."""
        self._stop_thinking()
        self._body.value = text
        if self.page:
            self._body.update()

    def set_components(self, controls: list[ft.Control]) -> None:
        """Attach in-conversation components below the message body."""
        self._components.controls = list(controls)
        self._components.visible = bool(controls)
        if self.page:
            self._components.update()

    def finalize(
        self,
        text: str,
        meta: dict[str, Any],
        tool_trace: list[dict[str, Any]] | None = None,
    ) -> None:
        """Pin the exact final text and show the attribution footer.

        With a trace, the live trail (previews and narration snippets) is
        rebuilt as clickable rows expanding to each run's full script and
        output - the same rows a history reload renders."""
        self._stop_thinking()
        self._body.value = text
        if tool_trace:
            self.set_tool_trace(tool_trace)
        line = footer_line(meta)
        if line:
            self._footer.value = line
            self._footer.visible = True
        if self.page:
            self.update()
