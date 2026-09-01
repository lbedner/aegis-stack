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
from app.components.frontend.controls.inputs import StyledTextField
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.controls.text import SecondaryText
from app.components.frontend.theme import AegisTheme as Theme
from app.core.log import logger
from app.core.sse import stream_sse_post

from .attachments_ui import AttachmentsMixin, attachment_payload
from .components import PendingChangeBatchCard, components_from_trace
from .history_ui import HistoryMixin
from .message import ChatMessageBubble
from .model_picker import ModelChipMixin
from .models import model_label
from .stream import (
    StreamAccumulator,
    narration_note,
    strip_attachment_marker,
    tool_label,
)

# Render at most this often while streaming; chunks buffer in between.
_RENDER_INTERVAL_SECONDS = 0.1


class ChatPanel(AttachmentsMixin, HistoryMixin, ModelChipMixin, ft.Container):
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
        self._input = StyledTextField(
            hint_text=f"Message {agent_name}",
            multiline=True,
            min_lines=1,
            max_lines=5,
            shift_enter=True,
            expand=True,
            on_submit=self._on_send,
        )
        self._send_button = BaseIconButton(
            self._send_current_input, ft.Icons.SEND, tooltip="Send"
        )
        self._build_attachment_controls()
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
                        ft.Container(content=self._jump_button, right=10, bottom=10),
                    ],
                    expand=True,
                ),
                self._attachment_bar,
                ft.Row(
                    [
                        self._model_chip,
                        self._input,
                        self._attach_button,
                        self._send_button,
                    ]
                ),
            ],
            expand=True,
            spacing=Theme.Spacing.SM,
        )
        self.expand = True
        # Every pending-change card the transcript currently shows, so a
        # return to this tab can re-read them - a resolution made on the
        # Overview tab must reach a card chat already rendered.
        self._pending_cards: list[ft.Control] = []

    # -- lifecycle ---------------------------------------------------------

    def _clear_transcript(self) -> None:
        self._transcript.controls.clear()
        self._pending_cards.clear()

    def refresh_on_revisit(self) -> None:
        if self.page and self._pending_cards:
            self.page.run_task(self._refresh_pending_cards)

    def _track_cards(self, cards: list[ft.Control]) -> None:
        """Register rendered cards and immediately re-read each from the
        queue: a card built from the trace's compact marker carries
        identity only - the server supplies the rows."""
        self._pending_cards.extend(cards)
        for card in cards:
            fetch = (
                self._batch_fetch
                if isinstance(card, PendingChangeBatchCard)
                else self._change_fetch
            )
            if self.page:
                self.page.run_task(card.refresh_from, fetch)

    async def _refresh_pending_cards(self) -> None:
        for card in list(self._pending_cards):
            fetch = (
                self._batch_fetch
                if isinstance(card, PendingChangeBatchCard)
                else self._change_fetch
            )
            await card.refresh_from(fetch)

    def did_mount(self) -> None:
        self._mount_attachments()
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
        self._clear_transcript()
        for message in detail.get("messages", []):
            role = message.get("role", "assistant")
            trace = (message.get("metadata") or {}).get("tool_trace")
            bubble = ChatMessageBubble(
                role=role,
                text=message.get("content", ""),
                agent_name=self.agent_name,
                tool_trace=trace,
                on_replay=self._replay,
            )
            if trace:
                cards = components_from_trace(
                    trace,
                    on_action=self._change_action,
                    on_batch_action=self._batch_action,
                    fetch_items=self._batch_fetch,
                )
                bubble.set_components(cards)
                # Snapshot state is propose-time state: a resolution made
                # on the Overview tab has to reach a reloaded chat card.
                self._track_cards(cards)
            self._transcript.controls.append(bubble.in_row())
        self._show_transcript()

    async def _start_new_conversation(self) -> None:
        self.conversation_id = None
        self._clear_transcript()
        self._body.content = self._empty_state
        if self.page:
            self.update()

    # -- streaming turn ----------------------------------------------------

    def _on_send(self, _event: ft.ControlEvent) -> None:
        """Enter-key submit path; the send button uses the async handler."""
        self.page.run_task(self._send_current_input)

    def _replay(
        self, text: str, attachments: list[dict[str, str]] | None = None
    ) -> None:
        """A user bubble's replay: the same text as a fresh turn, riding
        its retained images plus anything newly staged. A history-reloaded
        bubble has no retained bytes, so its stored marker is stripped
        rather than re-claimed."""
        if self._streaming:
            return
        resend = list(attachments or [])
        # A failed turn restages these same dicts as chips; equality
        # dedupe keeps a post-error replay from sending doubles.
        resend += [a for a in self._take_attachments() if a not in resend]
        self.page.run_task(self._run_turn, strip_attachment_marker(text), resend)

    async def _send_current_input(self) -> None:
        text = (self._input.value or "").strip()
        if self._streaming or (not text and not self._pending_attachments):
            return
        if not text:
            text = "See the attached images."
        self._input.value = ""
        await self._run_turn(text, attachments=self._take_attachments())

    async def _run_turn(
        self, text: str, attachments: list[dict[str, str]] | None = None
    ) -> None:
        attachments = attachments or []
        # Session-memory retention: this bubble's replay closure holds
        # this very list, so replaying re-sends the original images
        # until the bounded retainer evicts them.
        self._retained.retain(attachments)
        self._streaming = True
        self._send_button.update_state(disabled=True)
        self._transcript.controls.append(
            ChatMessageBubble(
                role="user",
                text=text,
                agent_name=self.agent_name,
                on_replay=lambda t, a=attachments: self._replay(t, a),
            ).in_row()
        )
        note = self._attachment_note_row(attachments)
        if note is not None:
            self._transcript.controls.append(note)
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
            "attachments": attachment_payload(attachments),
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

        if errored and attachments:
            # A failed turn must not eat its images: restage them so the
            # bubble's replay (or a plain resend) carries them again.
            self._pending_attachments.extend(attachments)
            self._refresh_attachment_chips()
        if not errored:
            if accumulator.conversation_id:
                self.conversation_id = accumulator.conversation_id
            reply.finalize(
                accumulator.final_text(),
                accumulator.final_meta,
                accumulator.tool_trace,
            )
            if accumulator.tool_trace:
                cards = components_from_trace(
                    accumulator.tool_trace,
                    on_action=self._change_action,
                    on_batch_action=self._batch_action,
                    fetch_items=self._batch_fetch,
                )
                reply.set_components(cards)
                self._track_cards(cards)
        self._scroll_to_latest()
        self._streaming = False
        self._send_button.update_state(disabled=False)
        if self.page:
            self._input.focus()

    async def _batch_fetch(self, batch_id: str) -> list[dict[str, Any]] | None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        response = await api.get(f"/api/v1/finance/changes/batch/{batch_id}")
        return response.get("items") if isinstance(response, dict) else None

    async def _batch_action(
        self, batch_id: str, action: str, exclude_ids: list[int]
    ) -> dict[str, Any] | None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        response = await api.post(
            f"/api/v1/finance/changes/batch/{batch_id}/{action}",
            json={"exclude_ids": exclude_ids} if action == "approve" else None,
        )
        if not isinstance(response, dict):
            ErrorSnackBar(api.last_error or "Could not resolve the batch.").launch(
                self.page
            )
            return None
        return response

    async def _change_fetch(self, change_id: int) -> dict[str, Any] | None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        response = await api.get(f"/api/v1/finance/changes/{change_id}")
        return response if isinstance(response, dict) else None

    async def _change_action(
        self, change_id: int, action: str
    ) -> dict[str, Any] | None:
        """Resolve one pending change and hand the card the queue's new
        truth. The endpoint is the finance write queue's - the only
        surface that currently proposes - and a stack without it simply
        never renders a card that could call this."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        response = await api.post(f"/api/v1/finance/changes/{change_id}/{action}")
        if not isinstance(response, dict):
            ErrorSnackBar(api.last_error or "Could not resolve the change.").launch(
                self.page
            )
            return None
        return response

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
