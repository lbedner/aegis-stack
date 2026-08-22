"""The embeddable chat panel: transcript, input, streaming, history.

API-only by design: every byte flows through the backend HTTP API
(``/api/v1/ai/chat/stream``, ``/api/v1/ai/conversations``), never through
in-process service calls. The panel is configured entirely by its agent
row - persona, tools, sampling, code mode all come from the DB - so a
surface embeds it with nothing but a slug and a surface name.
"""

import time
from typing import Any

import flet as ft

from app.components.frontend.controls.buttons import BaseIconButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import input_field_kwargs
from app.components.frontend.controls.text import PrimaryText, SecondaryText
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_relative_time
from app.core.log import logger
from app.core.sse import stream_sse_post

from .message import ChatMessageBubble
from .model_picker import ModelPickerDialog
from .models import model_label
from .stream import StreamAccumulator, narration_note, tool_label

# Render at most this often while streaming; chunks buffer in between.
_RENDER_INTERVAL_SECONDS = 0.1


class ChatPanel(ft.Container):
    """A self-contained chat surface bound to one agent row.

    Args:
        agent_slug: The agent row to speak as (None = default agent).
        surface: History scope for this embed (e.g. "finance"); new
            conversations are tagged with it and the drawer lists only
            this surface's past.
        agent_name: Display name for assistant bubbles.
        placeholder: Empty-state prompt shown before the first message.
        user_id: Conversation owner for history scoping.
    """

    def __init__(
        self,
        *,
        agent_slug: str | None = None,
        surface: str | None = None,
        agent_name: str = "Assistant",
        placeholder: str = "Ask anything about this workspace.",
        user_id: str = "api-user",
    ) -> None:
        super().__init__()
        self.agent_slug = agent_slug
        self.surface = surface
        self.agent_name = agent_name
        self.placeholder = placeholder
        self.user_id = user_id

        self.conversation_id: str | None = None
        self._auto_scroll = True
        self._streaming = False
        self._history_dialog: StyledAlertDialog | None = None

        self._transcript = ft.ListView(
            expand=True,
            spacing=Theme.Spacing.SM,
            padding=Theme.Spacing.SM,
            on_scroll=self._on_scroll,
        )
        self._jump_button = BaseIconButton(
            self._jump_to_bottom,
            ft.Icons.KEYBOARD_ARROW_DOWN,
            tooltip="Scroll to latest",
            visible=False,
        )
        self._empty_state = ft.Container(
            content=SecondaryText(placeholder),
            alignment=ft.alignment.center,
            expand=True,
        )
        self._input = ft.TextField(
            hint_text=f"Message {agent_name}",
            multiline=True,
            min_lines=1,
            max_lines=5,
            shift_enter=True,
            expand=True,
            on_submit=self._on_send,
            **input_field_kwargs("default", None),
        )
        self._send_button = BaseIconButton(
            self._send_current_input, ft.Icons.SEND, tooltip="Send"
        )
        self._model_chip_label = SecondaryText(
            model_label(None),
            size=Theme.Typography.BODY_SMALL,
            no_wrap=True,
            selectable=False,
        )
        self._model_chip = ft.Container(
            content=ft.Row(
                [
                    self._model_chip_label,
                    ft.Icon(
                        ft.Icons.ARROW_DROP_DOWN,
                        size=16,
                        color=Theme.Colors.TEXT_SECONDARY,
                    ),
                ],
                spacing=2,
                tight=True,
            ),
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.SM, vertical=Theme.Spacing.XS
            ),
            border_radius=Theme.Components.BUTTON_RADIUS,
            ink=True,
            tooltip="Switch the active model",
            on_click=lambda _event: self.page.run_task(self._open_model_picker),
        )
        self._model_dialog: StyledAlertDialog | None = None
        self._history_button = BaseIconButton(
            self._open_history,
            ft.Icons.HISTORY,
            tooltip="Conversation history",
        )
        self._new_button = BaseIconButton(
            self._start_new_conversation,
            ft.Icons.ADD_COMMENT_OUTLINED,
            tooltip="New conversation",
        )

        self._body = ft.Container(content=self._empty_state, expand=True)
        self.padding = ft.padding.symmetric(horizontal=Theme.Spacing.LG)
        self.content = ft.Column(
            [
                ft.Row(
                    [ft.Container(expand=True), self._new_button, self._history_button]
                ),
                ft.Stack(
                    [
                        self._body,
                        ft.Container(
                            content=self._jump_button, right=10, bottom=10
                        ),
                    ],
                    expand=True,
                ),
                ft.Row([self._model_chip, self._input, self._send_button]),
            ],
            expand=True,
            spacing=Theme.Spacing.SM,
        )
        self.expand = True

    # -- lifecycle ---------------------------------------------------------

    def did_mount(self) -> None:
        self.page.run_task(self._resume_latest)
        self.page.run_task(self._refresh_model_chip)

    def _api(self) -> Any:
        from app.components.frontend.state.session_state import get_session_state

        return get_session_state(self.page).api_client

    # -- history -----------------------------------------------------------

    async def _resume_latest(self) -> None:
        """Open onto the most recent conversation for this surface."""
        params: dict[str, Any] = {"user_id": self.user_id, "limit": 1}
        if self.surface:
            params["surface"] = self.surface
        conversations = await self._api().get("/api/v1/ai/conversations", params)
        if conversations:
            await self._load_conversation(conversations[0]["id"])

    async def _load_conversation(self, conversation_id: str) -> None:
        detail = await self._api().get(
            f"/api/v1/ai/conversations/{conversation_id}",
            {"user_id": self.user_id},
        )
        if detail is None:
            return
        self.conversation_id = conversation_id
        self._transcript.controls.clear()
        for message in detail.get("messages", []):
            role = message.get("role", "assistant")
            bubble = ChatMessageBubble(
                role=role,
                text=message.get("content", ""),
                agent_name=self.agent_name,
                tool_trace=(message.get("metadata") or {}).get("tool_trace"),
            )
            self._transcript.controls.append(bubble.in_row())
        self._show_transcript()

    def _history_row(self, conv: dict[str, Any]) -> ft.Control:
        async def pick() -> None:
            if self._history_dialog is not None:
                self._history_dialog.open = False
                self.page.update()
            await self._load_conversation(conv["id"])

        return ft.Container(
            content=ft.Column(
                [
                    PrimaryText(
                        conv.get("title") or conv["id"][:8],
                        no_wrap=True,
                        selectable=False,
                    ),
                    SecondaryText(
                        format_relative_time(conv.get("last_activity")),
                        size=Theme.Typography.BODY_SMALL,
                        selectable=False,
                    ),
                ],
                spacing=0,
                tight=True,
            ),
            padding=Theme.Spacing.SM,
            border_radius=Theme.Components.BUTTON_RADIUS,
            ink=True,
            on_click=lambda _event: self.page.run_task(pick),
        )

    async def _open_history(self) -> None:
        params: dict[str, Any] = {"user_id": self.user_id, "limit": 25}
        if self.surface:
            params["surface"] = self.surface
        conversations = await self._api().get("/api/v1/ai/conversations", params)
        rows: list[ft.Control] = [
            self._history_row(conv) for conv in (conversations or [])
        ]
        if not rows:
            rows = [SecondaryText("No conversations yet.")]
        async def _close_history() -> None:
            if self._history_dialog is not None:
                self._history_dialog.open = False
                self.page.update()

        self._history_dialog = StyledAlertDialog(
            title="Conversation history",
            body=ft.Container(
                content=ft.Column(rows, tight=True, scroll=ft.ScrollMode.AUTO),
                height=320,
            ),
            on_close=_close_history,
        )
        self.page.open(self._history_dialog)

    async def _start_new_conversation(self) -> None:
        self.conversation_id = None
        self._transcript.controls.clear()
        self._body.content = self._empty_state
        if self.page:
            self.update()

    # -- model selection ---------------------------------------------------

    async def _refresh_model_chip(self) -> None:
        current = await self._api().get("/api/v1/llm/current")
        self._model_chip_label.value = model_label(current)
        if self.page:
            self._model_chip_label.update()

    async def _pick_model(self, model_id: str) -> None:
        result = await self._api().post(
            "/api/v1/llm/current", {"model_id": model_id}
        )
        if not result or not result.get("success"):
            from app.components.frontend.controls.snack_bar import ErrorSnackBar

            detail = (result or {}).get("message") or "Model switch failed."
            self.page.open(ErrorSnackBar(detail))
            return
        if self._model_dialog is not None:
            self._model_dialog.open = False
        await self._refresh_model_chip()
        self.page.update()

    async def _close_model_picker(self) -> None:
        if self._model_dialog is not None:
            self._model_dialog.open = False
            self.page.update()

    async def _open_model_picker(self) -> None:
        models = await self._api().get(
            "/api/v1/llm/models", {"limit": 200, "usable": True}
        )
        vendors = await self._api().get("/api/v1/llm/vendors", {"usable": True})
        current = await self._api().get("/api/v1/llm/current")
        vendor_icons = {
            v["name"]: v["icon_b64"]
            for v in (vendors or [])
            if v.get("icon_b64")
        }
        self._model_dialog = ModelPickerDialog(
            models=models or [],
            vendor_icons=vendor_icons,
            active_id=str((current or {}).get("model") or ""),
            on_pick=self._pick_model,
            on_close=self._close_model_picker,
        )
        self.page.open(self._model_dialog)

    # -- streaming turn ----------------------------------------------------

    def _on_send(self, _event: ft.ControlEvent) -> None:
        """Enter-key submit path; the send button uses the async handler."""
        self.page.run_task(self._send_current_input)

    async def _send_current_input(self) -> None:
        text = (self._input.value or "").strip()
        if not text or self._streaming:
            return
        self._input.value = ""
        await self._run_turn(text)

    async def _run_turn(self, text: str) -> None:
        self._streaming = True
        self._send_button.update_state(disabled=True)
        self._transcript.controls.append(
            ChatMessageBubble(
                role="user", text=text, agent_name=self.agent_name
            ).in_row()
        )
        reply = ChatMessageBubble(role="assistant", agent_name=self.agent_name)
        self._transcript.controls.append(reply.in_row())
        self._show_transcript()
        reply.start_thinking()

        accumulator = StreamAccumulator()
        body: dict[str, Any] = {
            "message": text,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "agent_slug": self.agent_slug,
            "surface": self.surface,
        }
        last_render = 0.0
        errored = False
        try:
            async for event, payload in stream_sse_post(
                self._api(), "/api/v1/ai/chat/stream", body
            ):
                if event == "chunk":
                    accumulator.add_chunk(payload)
                    now = time.monotonic()
                    if now - last_render >= _RENDER_INTERVAL_SECONDS:
                        last_render = now
                        reply.set_streaming_text(accumulator.snapshot())
                        self._scroll_to_latest()
                elif event == "tool":
                    # A tool call: fold the streamed pre-tool narration
                    # into the trail (so it doesn't just vanish), then
                    # append the call itself.
                    note = narration_note(accumulator.text)
                    accumulator.reset_text()
                    if note:
                        reply.add_tool_call(note)
                    reply.add_tool_call(
                        tool_label(payload.get("tool", ""), payload.get("args", ""))
                    )
                    self._scroll_to_latest()
                elif event == "final":
                    accumulator.add_final(payload)
                elif event == "error":
                    errored = True
                    detail = payload.get("detail") or payload.get("error", "")
                    reply.set_streaming_text(
                        f"Something went wrong answering that. {detail}".strip()
                    )
        except Exception as exc:  # noqa: BLE001 - a dead turn must not kill the panel
            errored = True
            logger.warning("chat_panel.turn_failed", error=str(exc))
            reply.set_streaming_text("Something went wrong answering that.")

        if not errored:
            if accumulator.conversation_id:
                self.conversation_id = accumulator.conversation_id
            reply.finalize(
                accumulator.final_text(),
                accumulator.final_meta,
                accumulator.tool_trace,
            )
        self._scroll_to_latest()
        self._streaming = False
        self._send_button.update_state(disabled=False)
        if self.page:
            self._input.focus()

    # -- scroll behavior ---------------------------------------------------

    def _show_transcript(self) -> None:
        if self._body.content is not self._transcript:
            self._body.content = self._transcript
        if self.page:
            self.update()
            self._scroll_to_latest()

    def _on_scroll(self, event: ft.OnScrollEvent) -> None:
        at_bottom = event.pixels + 24 >= event.max_scroll_extent
        if at_bottom != self._auto_scroll:
            self._auto_scroll = at_bottom
            self._jump_button.visible = not at_bottom
            self._jump_button.update()

    def _scroll_to_latest(self) -> None:
        if self._auto_scroll and self.page:
            self._transcript.scroll_to(offset=-1, duration=150)

    async def _jump_to_bottom(self) -> None:
        self._auto_scroll = True
        self._jump_button.visible = False
        if self.page:
            self._jump_button.update()
            self._transcript.scroll_to(offset=-1, duration=300)
