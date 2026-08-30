"""In-conversation components: typed data in, system-rendered control out.

The generative-UI foundation. A tool result (or any structured payload)
carries DATA; presentation is system code selected by ``kind`` from the
registry below. The model never authors layout, and a kind the frontend
does not know degrades to absence - never a crash, never a raw dict on
screen.

The pending-change card (FW-05) is the first kind. It renders the
STORED queue row - the same row approval executes - so what the user
sees and what runs cannot diverge. New kinds (previews, dry-run diffs)
register here; nothing else changes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
import re
from typing import Any

import flet as ft

from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.text import LabelText, SecondaryText
from app.components.frontend.theme import AegisTheme as Theme

# on_action(change_id, "approve" | "reject") -> the updated change dict
# (the API response), or None when the call failed and the card should
# stay actionable.
ChangeAction = Callable[[int, str], Awaitable[dict[str, Any] | None]]

# A confirmation is a focused decision, not a banner: the card keeps a
# fixed narrow width and centers in whatever column hosts it.
CARD_WIDTH = 420

_STATUS_COPY = {
    "pending": ("Awaiting your approval", Theme.Colors.WARNING),
    "approved": ("Approved", Theme.Colors.SUCCESS),
    "rejected": ("Rejected", Theme.Colors.ERROR),
    "expired": ("Expired", ft.Colors.OUTLINE),
}


BatchAction = Callable[[str, str, list[int]], Awaitable[dict[str, Any] | None]]

_ARROW = " \u2192 "


def _value_text(value: str, *, color: str, **kwargs: Any) -> SecondaryText:
    """A display value; a "before \u2192 after" line gets its target in
    accent teal so the eye lands on what will change."""
    if _ARROW not in value:
        return SecondaryText(value, color=color, **kwargs)
    before, _, target = value.rpartition(_ARROW)
    return SecondaryText(
        "",
        color=color,
        spans=[
            ft.TextSpan(before + _ARROW),
            ft.TextSpan(target, style=ft.TextStyle(color=Theme.Colors.ACCENT)),
        ],
        **kwargs,
    )


class PendingChangeBatchCard(ft.Container):
    """One decision over many rows: every proposal in the batch as a
    compact line with a per-row veto, and bulk actions whose copy says
    exactly how many will land. Resolved batches read as an outcome
    summary - the audit lives on the individual rows.
    """

    def __init__(
        self,
        data: dict[str, Any],
        on_batch_action: BatchAction,
        fetch_items: Callable[[str], Awaitable[list[dict[str, Any]] | None]]
        | None = None,
    ) -> None:
        super().__init__(
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            padding=ft.padding.symmetric(
                vertical=Theme.Spacing.SM, horizontal=Theme.Spacing.MD
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            width=CARD_WIDTH,
            margin=ft.margin.symmetric(
                vertical=Theme.Spacing.XS, horizontal=Theme.Spacing.SM
            ),
        )
        self._on_batch_action = on_batch_action
        self._fetch_items = fetch_items
        self._batch_id = str(data.get("batch_id") or "")
        self._title = str(data.get("title") or data.get("change_type") or "Changes")
        self._excluded: set[int] = set()
        self._expanded = False
        self.render(data.get("items") or [])

    def toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self.render(self._items)
        if self.page:
            self.update()

    def toggle_veto(self, change_id: int) -> None:
        if change_id in self._excluded:
            self._excluded.discard(change_id)
        else:
            self._excluded.add(change_id)
        self.render(self._items)
        if self.page:
            self.update()

    async def refresh_from(
        self, fetch: Callable[[str], Awaitable[list[dict[str, Any]] | None]]
    ) -> None:
        items = await fetch(self._batch_id)
        if items is not None:
            self.render(items)
            if self.page:
                self.update()

    @staticmethod
    def _outcome_summary(items: list[dict[str, Any]]) -> str:
        """ "1 approved, 1 rejected" - the resolved batch's one-line story."""
        counts: dict[str, int] = {}
        for item in items:
            counts[str(item.get("status"))] = counts.get(str(item.get("status")), 0) + 1
        return ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))

    def _row_line(self, item: dict[str, Any]) -> str:
        return "  \u00b7  ".join(
            str(line.get("value", "")) for line in item.get("display") or []
        )

    def render(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        pending = [i for i in items if i.get("status") == "pending"]
        header: list[ft.Control] = [
            LabelText(f"{self._title} ({len(items)})"),
            ft.Container(expand=True),
            SecondaryText(
                (_STATUS_COPY["pending"][0] if pending else "Resolved"),
                color=(_STATUS_COPY["pending"][1] if pending else ft.Colors.OUTLINE),
            ),
        ]
        if not pending:
            header.append(
                ft.IconButton(
                    icon=(
                        ft.Icons.EXPAND_LESS if self._expanded else ft.Icons.EXPAND_MORE
                    ),
                    icon_size=16,
                    width=28,
                    height=28,
                    padding=0,
                    on_click=lambda _e: self.toggle_expanded(),
                )
            )
        rows: list[ft.Control] = [
            ft.Row(header, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        ]
        if not pending and not self._expanded:
            rows.append(SecondaryText(self._outcome_summary(items)))
            self.content = ft.Column(rows, spacing=Theme.Spacing.SM, tight=True)
            return
        for item in items:
            item_id = int(item.get("id") or 0)
            status = str(item.get("status", "pending"))
            vetoed = item_id in self._excluded
            dimmed = vetoed or status == "rejected"
            line = (
                SecondaryText(self._row_line(item), color=ft.Colors.OUTLINE)
                if dimmed
                else _value_text(self._row_line(item), color=ft.Colors.ON_SURFACE)
            )
            trailing: ft.Control
            if status == "pending":
                trailing = ft.TextButton(
                    "veto" if not vetoed else "keep",
                    on_click=lambda _e, cid=item_id: self.toggle_veto(cid),
                )
            else:
                copy, color = _STATUS_COPY.get(
                    status, (status.title(), ft.Colors.OUTLINE)
                )
                trailing = SecondaryText(copy, color=color)
            rows.append(
                ft.Row(
                    [ft.Container(content=line, expand=True), trailing],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        if pending:
            landing = len(pending) - len(
                self._excluded & {int(i.get("id") or 0) for i in pending}
            )

            async def _act(action: str) -> None:
                summary = await self._on_batch_action(
                    self._batch_id, action, sorted(self._excluded)
                )
                if summary is None:
                    return
                if self._fetch_items is not None:
                    await self.refresh_from(self._fetch_items)

            rows.append(
                ft.Row(
                    [
                        ft.Container(expand=True),
                        PulseButton(
                            on_click_callable=lambda: _act("reject"),
                            text="Reject all",
                            variant="muted",
                            compact=True,
                        ),
                        PulseButton(
                            on_click_callable=lambda: _act("approve"),
                            text=f"Approve all ({landing})",
                            variant="teal",
                            compact=True,
                        ),
                    ],
                    spacing=Theme.Spacing.SM,
                )
            )
        else:
            rows.append(SecondaryText(self._outcome_summary(items)))
        self.content = ft.Column(rows, spacing=Theme.Spacing.SM, tight=True)


class PendingChangeCard(ft.Container):
    """One proposed mutation, from pending through resolution.

    ``render(data)`` rebuilds the card from a change dict (the API's
    ``PendingChangeResponse`` shape); the action buttons call
    ``on_action`` and re-render from whatever it returns, so the card
    always shows the queue's truth, never an optimistic guess.
    """

    def __init__(self, data: dict[str, Any], on_action: ChangeAction) -> None:
        super().__init__(
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            padding=ft.padding.symmetric(
                vertical=Theme.Spacing.SM, horizontal=Theme.Spacing.MD
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            width=CARD_WIDTH,
            margin=ft.margin.symmetric(
                vertical=Theme.Spacing.XS, horizontal=Theme.Spacing.SM
            ),
        )
        self._on_action = on_action
        self._change_id = int(data.get("id") or data.get("pending_change_id") or 0)
        self._expanded = False
        self.render(data)

    def toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self.render(self._data)
        if self.page:
            self.update()

    async def refresh_from(
        self, fetch: Callable[[int], Awaitable[dict[str, Any] | None]]
    ) -> None:
        """Re-render from the queue's current truth.

        A card rebuilt from a history snapshot shows propose-time state;
        a resolution made on another surface (the Overview tab) has to
        reach it. A failed fetch changes nothing - the snapshot stays.
        """
        data = await fetch(self._change_id)
        if data is not None:
            self.render(data)
            if self.page:
                self.update()

    def render(self, data: dict[str, Any]) -> None:
        self._data = data
        status = str(data.get("status", "pending"))
        copy, color = _STATUS_COPY.get(status, (status.title(), ft.Colors.OUTLINE))
        resolved = status != "pending"
        header: list[ft.Control] = [
            LabelText(str(data.get("title") or data.get("change_type", ""))),
            ft.Container(expand=True),
            SecondaryText(copy, color=color),
        ]
        if resolved:
            # A decided card is history, not homework: it folds to this
            # line automatically, expandable on demand.
            header.append(
                ft.IconButton(
                    icon=(
                        ft.Icons.EXPAND_LESS if self._expanded else ft.Icons.EXPAND_MORE
                    ),
                    icon_size=16,
                    width=28,
                    height=28,
                    padding=0,
                    on_click=lambda _e: self.toggle_expanded(),
                )
            )
        rows: list[ft.Control] = [
            ft.Row(header, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        ]
        if resolved and not self._expanded:
            self.content = ft.Column(rows, spacing=Theme.Spacing.SM, tight=True)
            return
        for line in data.get("display") or []:
            # The value gets the row's remaining width and WRAPS: a long
            # before -> after line clipped at the card edge is exactly
            # the half-truth a confirmation cannot afford.
            rows.append(
                ft.Row(
                    [
                        SecondaryText(str(line.get("label", ""))),
                        ft.Container(
                            content=_value_text(
                                str(line.get("value", "")),
                                color=ft.Colors.ON_SURFACE,
                                text_align=ft.TextAlign.RIGHT,
                            ),
                            expand=True,
                        ),
                    ],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
            )
        error = data.get("error")
        if error:
            rows.append(SecondaryText(str(error), color=Theme.Colors.ERROR))
        if status == "pending":
            change_id = int(data.get("id") or data.get("pending_change_id") or 0)

            async def _act(action: str) -> None:
                updated = await self._on_action(change_id, action)
                if updated is not None:
                    self.render(updated)
                    if self.page:
                        self.update()

            rows.append(
                ft.Row(
                    [
                        ft.Container(expand=True),
                        PulseButton(
                            on_click_callable=lambda: _act("reject"),
                            text="Reject",
                            variant="muted",
                            compact=True,
                        ),
                        PulseButton(
                            on_click_callable=lambda: _act("approve"),
                            text="Approve",
                            variant="teal",
                            compact=True,
                        ),
                    ],
                    spacing=Theme.Spacing.SM,
                )
            )
        self.content = ft.Column(rows, spacing=Theme.Spacing.SM, tight=True)


def render_component(
    kind: str,
    data: dict[str, Any],
    *,
    on_action: ChangeAction,
    on_batch_action: BatchAction | None = None,
    fetch_items: Callable[[str], Awaitable[list[dict[str, Any]] | None]] | None = None,
) -> ft.Control | None:
    """The registry's one door: a control for a known kind, None for an
    unknown one."""
    if kind == "pending_change":
        return PendingChangeCard(data, on_action)
    if kind == "pending_change_batch" and on_batch_action is not None:
        return PendingChangeBatchCard(data, on_batch_action, fetch_items=fetch_items)
    return None


def _salvage_identity(clipped: str) -> dict[str, Any] | None:
    """Identity fields from a truncated proposal result, or None."""
    fields: dict[str, Any] = {}
    for key in ("batch_id", "change_type", "title", "status"):
        m = re.search(rf'"{key}":\s*"([^"]*)"', clipped)
        if m:
            fields[key] = m.group(1)
    m = re.search(r'"pending_change_id":\s*(\d+)', clipped)
    if m:
        fields["pending_change_id"] = int(m.group(1))
    if fields.get("batch_id"):
        return {**fields, "items": []}
    if fields.get("pending_change_id"):
        return {"status": "pending", "display": [], **fields}
    return None


def components_from_trace(
    trace: list[dict[str, Any]],
    *,
    on_action: ChangeAction,
    on_batch_action: BatchAction | None = None,
    fetch_items: Callable[[str], Awaitable[list[dict[str, Any]] | None]] | None = None,
) -> list[ft.Control]:
    """Cards for the trace's propose results.

    The tool trail is the transport: a ``propose`` (or ``propose_many``)
    call's result IS the pending-change data. Anything that does not
    parse as one is left to the trail's ordinary rendering.
    """
    cards: list[ft.Control] = []
    for entry in trace:
        if entry.get("tool") not in ("propose", "propose_many"):
            continue
        # The compact marker is the contract: the result blob is
        # display-clipped and a big batch truncates to invalid JSON.
        # Cards built from the marker refresh their rows from the
        # queue; parsing the result is the legacy fallback for traces
        # recorded before the marker existed.
        data: dict[str, Any] | None = None
        marker = entry.get("component")
        if isinstance(marker, dict) and marker.get("kind"):
            data = {**marker, "items": []}
        else:
            result = entry.get("result")
            if not isinstance(result, str):
                continue
            try:
                parsed = json.loads(result)
            except (TypeError, ValueError):
                # Pre-marker traces clipped big results to invalid
                # JSON. The identity fields lead the blob, so they
                # survive the clip - salvage them; the card fetches
                # its rows from the queue like any marker card.
                parsed = _salvage_identity(result)
            if isinstance(parsed, dict):
                data = parsed
        if data is None:
            continue
        card: ft.Control | None = None
        if "batch_id" in data and isinstance(data.get("items"), list):
            card = render_component(
                "pending_change_batch",
                data,
                on_action=on_action,
                on_batch_action=on_batch_action,
                fetch_items=fetch_items,
            )
        elif "pending_change_id" in data:
            card = render_component("pending_change", data, on_action=on_action)
        if card is not None:
            cards.append(card)
    return cards
