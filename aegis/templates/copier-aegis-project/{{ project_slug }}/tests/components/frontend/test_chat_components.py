"""In-conversation components: typed data in, system-rendered control out.

The generative-UI foundation (FW-05): the model contributes DATA (via
tool results); presentation is system code keyed by ``kind``. The
pending-change card is the first kind - it renders the stored queue
row, which is exactly what approval executes, so what the user sees and
what runs cannot diverge.
"""

from typing import Any

from tests.components.frontend._tree import rendered

_CHANGE = {
    "id": 7,
    "change_type": "transaction.categorize",
    "title": "Categorize a transaction",
    "status": "pending",
    "display": [
        {"label": "Transaction", "value": "Shelly's Deli ($8.97 on 2026-06-10)"},
        {"label": "Category", "value": "Food & Dining:Eating Out"},
    ],
}


async def _noop_action(change_id: int, action: str) -> dict[str, Any] | None:
    return None


class TestComponentRegistry:
    def test_a_known_kind_renders(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        card = render_component("pending_change", _CHANGE, on_action=_noop_action)
        assert card is not None
        assert "Categorize a transaction" in rendered(card)

    def test_an_unknown_kind_renders_nothing(self) -> None:
        """A payload the frontend does not understand degrades to
        absence, never to a crash or a raw dict on screen."""
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        assert render_component("hologram", {"x": 1}, on_action=_noop_action) is None


class TestPendingChangeCard:
    def test_a_pending_card_shows_the_stored_row_and_both_actions(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        card = render_component("pending_change", _CHANGE, on_action=_noop_action)
        text = rendered(card)
        assert "Shelly's Deli ($8.97 on 2026-06-10)" in text
        assert "Food & Dining:Eating Out" in text
        assert "Approve" in text
        assert "Reject" in text

    def test_a_resolved_card_drops_the_actions(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )
        from tests.components.frontend._tree import texts

        resolved = {**_CHANGE, "status": "approved"}
        card = render_component("pending_change", resolved, on_action=_noop_action)
        tokens = texts(card)
        assert "Approved" in tokens  # the status chip
        assert "Approve" not in tokens  # the button label, gone
        assert "Reject" not in tokens

    def test_an_execution_error_is_shown_on_the_card(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        errored = {**_CHANGE, "error": "Transaction 999 not found."}
        card = render_component("pending_change", errored, on_action=_noop_action)
        assert "Transaction 999 not found." in rendered(card)


class TestTraceExtraction:
    def test_propose_calls_become_cards_and_other_tools_do_not(self) -> None:
        """The trail is the transport: a propose result carries the
        pending-change data, and the renderer turns exactly those
        entries into cards."""
        import json

        from app.components.frontend.controls.chat.components import (
            components_from_trace,
        )

        trace = [
            {"tool": "ledger", "args": "months=3", "result": "{...}"},
            {
                "tool": "propose",
                "args": "",
                "result": json.dumps(
                    {
                        "pending_change_id": 7,
                        "change_type": "transaction.categorize",
                        "title": "Categorize a transaction",
                        "status": "pending",
                        "display": _CHANGE["display"],
                    }
                ),
            },
            {"tool": "propose", "args": "", "result": "not json at all"},
        ]

        cards = components_from_trace(trace, on_action=_noop_action)

        assert len(cards) == 1
        assert "Categorize a transaction" in rendered(cards[0])


class TestCardGeometry:
    def test_the_card_is_narrow_and_never_message_width(self) -> None:
        """A confirmation is a focused decision, not a banner: the card
        holds a fixed narrow width instead of stretching across the
        transcript."""
        from app.components.frontend.controls.chat.components import (
            CARD_WIDTH,
            render_component,
        )

        card = render_component("pending_change", _CHANGE, on_action=_noop_action)
        assert card.width == CARD_WIDTH
        assert CARD_WIDTH <= 440


class TestCardStateSync:
    def test_a_history_card_refreshes_to_the_queues_truth(self) -> None:
        """A card rendered from a history snapshot says whatever was
        true at propose time; acting on another surface must reach it.
        ``refresh_from`` re-renders from a queue fetch."""
        import asyncio

        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        card = render_component("pending_change", _CHANGE, on_action=_noop_action)
        assert "Approve" in rendered(card)

        async def fetch(change_id: int):
            assert change_id == 7
            return {**_CHANGE, "status": "approved"}

        asyncio.run(card.refresh_from(fetch))

        text = rendered(card)
        assert "Approved" in text
        assert "Reject" not in text

    def test_a_failed_fetch_leaves_the_card_alone(self) -> None:
        import asyncio

        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        card = render_component("pending_change", _CHANGE, on_action=_noop_action)

        async def fetch(change_id: int):
            return None

        asyncio.run(card.refresh_from(fetch))
        assert "Approve" in rendered(card)


_BATCH = {
    "batch_id": "b-1",
    "change_type": "transaction.categorize",
    "title": "Categorize a transaction",
    "items": [
        {
            "id": 11,
            "status": "pending",
            "display": [
                {"label": "Transaction", "value": "Store 0 ($10.00 on 2026-08-01)"},
                {"label": "Category", "value": "Uncategorized \u2192 Groceries"},
            ],
        },
        {
            "id": 12,
            "status": "pending",
            "display": [
                {"label": "Transaction", "value": "Store 1 ($11.00 on 2026-08-02)"},
                {"label": "Category", "value": "Uncategorized \u2192 Groceries"},
            ],
        },
    ],
}


async def _noop_batch_action(batch_id, action, exclude_ids):
    return None


class TestBatchCard:
    def _card(self):
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        return render_component(
            "pending_change_batch",
            _BATCH,
            on_action=_noop_action,
            on_batch_action=_noop_batch_action,
        )

    def test_a_batch_renders_every_row_and_both_bulk_actions(self) -> None:
        card = self._card()
        text = rendered(card)
        assert "Store 0" in text and "Store 1" in text
        assert "Approve all (2)" in text
        assert "Reject all" in text

    def test_a_veto_shrinks_the_approve_count(self) -> None:
        """Vetoing a row is a per-row decision inside the one bulk
        decision: the approve button says exactly how many will land."""
        card = self._card()
        card.toggle_veto(11)
        assert "Approve all (1)" in rendered(card)
        card.toggle_veto(11)
        assert "Approve all (2)" in rendered(card)

    def test_a_resolved_batch_shows_the_outcome_summary(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        resolved = {
            **_BATCH,
            "items": [
                {**_BATCH["items"][0], "status": "approved"},
                {**_BATCH["items"][1], "status": "rejected"},
            ],
        }
        card = render_component(
            "pending_change_batch",
            resolved,
            on_action=_noop_action,
            on_batch_action=_noop_batch_action,
        )
        text = rendered(card)
        assert "1 approved" in text
        assert "1 rejected" in text
        assert "Approve all" not in text


class TestBatchTraceExtraction:
    def test_a_propose_many_result_becomes_one_batch_card(self) -> None:
        import json

        from app.components.frontend.controls.chat.components import (
            components_from_trace,
        )

        trace = [
            {"tool": "propose_many", "args": "", "result": json.dumps(_BATCH)},
        ]
        cards = components_from_trace(
            trace, on_action=_noop_action, on_batch_action=_noop_batch_action
        )
        assert len(cards) == 1
        assert "Approve all (2)" in rendered(cards[0])


class TestResolvedCardsCollapse:
    def test_a_resolved_card_collapses_to_one_line(self) -> None:
        """A decided card is history, not homework: it folds to its
        title and outcome, expandable on demand."""
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        card = render_component(
            "pending_change",
            {**_CHANGE, "status": "approved"},
            on_action=_noop_action,
        )
        text = rendered(card)
        assert "Categorize a transaction" in text
        assert "Approved" in text
        assert "Shelly's Deli" not in text  # detail folded away

    def test_the_fold_opens_on_demand(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        card = render_component(
            "pending_change",
            {**_CHANGE, "status": "approved"},
            on_action=_noop_action,
        )
        card.toggle_expanded()
        assert "Shelly's Deli" in rendered(card)
        card.toggle_expanded()
        assert "Shelly's Deli" not in rendered(card)

    def test_a_pending_card_never_collapses(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        card = render_component("pending_change", _CHANGE, on_action=_noop_action)
        assert "Shelly's Deli" in rendered(card)

    def test_a_resolved_batch_collapses_to_its_summary(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        resolved = {
            **_BATCH,
            "items": [
                {**_BATCH["items"][0], "status": "approved"},
                {**_BATCH["items"][1], "status": "rejected"},
            ],
        }
        card = render_component(
            "pending_change_batch",
            resolved,
            on_action=_noop_action,
            on_batch_action=_noop_batch_action,
        )
        text = rendered(card)
        assert "1 approved" in text
        assert "Store 0" not in text  # rows folded away
        card.toggle_expanded()
        assert "Store 0" in rendered(card)


class TestTargetCategoryHighlight:
    """A "before → after" value renders its target in accent teal: the
    eye lands on what will change, not on the prose around it."""

    @staticmethod
    def _accent_texts(card: Any) -> list[str]:
        from app.components.frontend.theme import AegisTheme as Theme
        from tests.components.frontend._tree import accent_texts

        return accent_texts(card, Theme.Colors.ACCENT)

    def test_the_single_card_target_is_teal(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        change = {
            **_CHANGE,
            "display": [
                {"label": "Transaction", "value": "Shelly's Deli ($8.97)"},
                {
                    "label": "Category",
                    "value": "Uncategorized \u2192 Food & Dining:Eating Out",
                },
            ],
        }
        card = render_component("pending_change", change, on_action=_noop_action)
        assert "Food & Dining:Eating Out" in self._accent_texts(card)
        text = rendered(card)
        assert "Uncategorized \u2192 " in text
        assert "Food & Dining:Eating Out" in text

    def test_a_batch_row_target_is_teal(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        card = render_component(
            "pending_change_batch",
            _BATCH,
            on_action=_noop_action,
            on_batch_action=_noop_batch_action,
        )
        accents = self._accent_texts(card)
        assert any("Groceries" in t for t in accents)

    def test_a_rejected_row_stays_dim(self) -> None:
        """Teal marks what WILL happen; a rejected row won't."""
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        rejected = {
            **_BATCH,
            "items": [{**i, "status": "rejected"} for i in _BATCH["items"]],
        }
        card = render_component(
            "pending_change_batch",
            rejected,
            on_action=_noop_action,
            on_batch_action=_noop_batch_action,
        )
        card.toggle_expanded()
        assert self._accent_texts(card) == []


_SPLIT_CHANGE = {
    "id": 9,
    "pending_change_id": 9,
    "change_type": "transaction.split",
    "title": "Split a transaction",
    "status": "pending",
    "display": [
        {"label": "Transaction", "value": "Target ($20.47 on Aug 27, 2026)"},
        {"label": "School supplies", "value": "$3.99"},
        {"label": "Groceries", "value": "$16.48"},
    ],
}

_SPLIT_BATCH = {
    "batch_id": "b-split",
    "change_type": "transaction.split",
    "title": "Split a transaction",
    "items": [
        {
            "id": 21,
            "status": "pending",
            "display": _SPLIT_CHANGE["display"],
        },
    ],
}


class TestReadableDetailRows:
    """A card's detail rows read as a person's line items, not a
    dot-joined log line: each row keeps its own label and lands on its
    own line. A plain (non-arrow) value is new information being
    proposed, so it pops in accent teal the same way an arrow's target
    does; the subject line (payee/amount/date) is context, never teal."""

    @staticmethod
    def _teal(card: Any) -> list[str]:
        from app.components.frontend.theme import AegisTheme as Theme
        from tests.components.frontend._tree import accent_texts

        return accent_texts(card, Theme.Colors.ACCENT)

    def test_the_single_card_keeps_each_split_line_separate(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        card = render_component(
            "pending_change", _SPLIT_CHANGE, on_action=_noop_action
        )

        assert "School supplies" in rendered(card)
        assert "Groceries" in rendered(card)
        # Never flattened into one dot-joined blob.
        assert "School supplies  ·" not in rendered(card)

    def test_a_memo_carrying_value_teals_only_the_price(self) -> None:
        """"$3.99 · groceries" highlights the money, not the prose - a
        wall of teal marks nothing."""
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        change = {
            **_SPLIT_CHANGE,
            "display": [
                _SPLIT_CHANGE["display"][0],
                {"label": "Groceries", "value": "$3.99 · root beer and candy"},
            ],
        }
        card = render_component("pending_change", change, on_action=_noop_action)

        teal = self._teal(card)
        assert "$3.99" in teal
        assert not any("root beer" in t for t in teal)
        assert "root beer and candy" in rendered(card)

    def test_the_single_card_teals_plain_values_but_not_the_subject(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        card = render_component(
            "pending_change", _SPLIT_CHANGE, on_action=_noop_action
        )

        teal = self._teal(card)
        assert "$3.99" in teal
        assert "$16.48" in teal
        assert "Target ($20.47 on Aug 27, 2026)" not in teal

    def test_the_batch_card_keeps_each_split_line_separate_and_teal(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        card = render_component(
            "pending_change_batch",
            _SPLIT_BATCH,
            on_action=_noop_action,
            on_batch_action=_noop_batch_action,
        )

        text = rendered(card)
        assert "School supplies" in text
        assert "Groceries" in text
        assert "School supplies  ·" not in text
        teal = self._teal(card)
        assert "$3.99" in teal
        assert "$16.48" in teal
        assert "Target ($20.47 on Aug 27, 2026)" not in teal

    def test_pending_labels_are_not_border_colored(self) -> None:
        """OUTLINE is a border token, near-invisible as body text on a
        dark card - a live label needs SecondaryText's own legible
        default, not that."""
        import flet as ft

        from app.components.frontend.controls.chat.components import (
            render_component,
        )
        from tests.components.frontend._tree import walk

        card = render_component(
            "pending_change_batch",
            _SPLIT_BATCH,
            on_action=_noop_action,
            on_batch_action=_noop_batch_action,
        )
        label = next(
            n for n in walk(card) if getattr(n, "value", None) == "School supplies"
        )
        assert label.color != ft.Colors.OUTLINE

    def test_a_rejected_batch_item_never_highlights(self) -> None:
        from app.components.frontend.controls.chat.components import (
            render_component,
        )

        rejected = {
            **_SPLIT_BATCH,
            "items": [{**_SPLIT_BATCH["items"][0], "status": "rejected"}],
        }
        card = render_component(
            "pending_change_batch",
            rejected,
            on_action=_noop_action,
            on_batch_action=_noop_batch_action,
        )
        card.toggle_expanded()

        assert self._teal(card) == []


class TestMarkerTraceExtraction:
    """The card builds from the trace's compact marker when present -
    the clipped result blob is display-only and may be truncated JSON."""

    def test_a_marker_builds_the_batch_card_despite_a_mangled_result(self) -> None:
        from app.components.frontend.controls.chat.components import (
            components_from_trace,
        )

        trace = [
            {
                "tool": "propose_many",
                "args": "",
                "result": '{"batch_id": "b-9", "items": [{"trunca',
                "component": {
                    "kind": "pending_change_batch",
                    "batch_id": "b-9",
                    "change_type": "transaction.tag",
                    "title": "Tag a transaction",
                    "count": 9,
                },
            },
        ]
        cards = components_from_trace(
            trace, on_action=_noop_action, on_batch_action=_noop_batch_action
        )
        assert len(cards) == 1
        assert cards[0]._batch_id == "b-9"

    def test_a_single_marker_builds_the_single_card(self) -> None:
        from app.components.frontend.controls.chat.components import (
            components_from_trace,
        )

        trace = [
            {
                "tool": "propose",
                "args": "",
                "result": "not json at all",
                "component": {
                    "kind": "pending_change",
                    "pending_change_id": 7,
                    "change_type": "transaction.categorize",
                    "title": "Categorize a transaction",
                    "status": "pending",
                },
            },
        ]
        cards = components_from_trace(trace, on_action=_noop_action)
        assert len(cards) == 1
        assert cards[0]._change_id == 7

    def test_a_pre_marker_truncated_result_still_yields_the_card(self) -> None:
        """Traces recorded before the marker existed clipped big batch
        results to invalid JSON. The identity fields lead the blob, so
        they survive the clip - salvage them and let the card fetch its
        rows from the queue."""
        from app.components.frontend.controls.chat.components import (
            components_from_trace,
        )

        result = (
            '{"batch_id": "97d8b137-ba64", "change_type": "transaction.tag", '
            '"title": "Tag a transaction", "count": 9, "items": [{"id": 12, '
            '"display": [{"label": "Transaction", "value": "trunca'
        )
        trace = [{"tool": "propose_many", "args": "", "result": result}]
        cards = components_from_trace(
            trace, on_action=_noop_action, on_batch_action=_noop_batch_action
        )
        assert len(cards) == 1
        assert cards[0]._batch_id == "97d8b137-ba64"
        assert "Tag a transaction" in rendered(cards[0])


class TestReplayAffordance:
    """The user bubble's replay control: same text again, one click."""

    def _replay_buttons(self, bubble: Any) -> list[Any]:
        from tests.components.frontend._tree import walk

        return [
            node
            for node in walk(bubble)
            if getattr(node, "tooltip", None) == "Send this message again"
        ]

    def test_user_bubbles_with_a_handler_offer_replay(self) -> None:
        from app.components.frontend.controls.chat.message import ChatMessageBubble

        bubble = ChatMessageBubble(
            role="user", text="split this", on_replay=lambda _text: None
        )

        assert len(self._replay_buttons(bubble)) == 1

    def test_replay_fires_with_the_message_text(self) -> None:
        from app.components.frontend.controls.chat.message import ChatMessageBubble

        seen: list[str] = []
        bubble = ChatMessageBubble(
            role="user", text="split this", on_replay=seen.append
        )

        (button,) = self._replay_buttons(bubble)
        button.on_click(None)

        assert seen == ["split this"]

    def test_assistant_bubbles_and_handlerless_user_bubbles_do_not(self) -> None:
        from app.components.frontend.controls.chat.message import ChatMessageBubble

        assistant = ChatMessageBubble(
            role="assistant", text="hi", on_replay=lambda _text: None
        )
        plain_user = ChatMessageBubble(role="user", text="hi")

        assert self._replay_buttons(assistant) == []
        assert self._replay_buttons(plain_user) == []


class TestReplayRetention:
    """Sent images stay replayable in session memory - bounded, and
    cleared IN PLACE on eviction so bubble closures see them vanish."""

    def test_retained_lists_stay_intact_under_the_cap(self) -> None:
        from app.components.frontend.controls.chat.attachments_ui import (
            ReplayRetention,
        )

        retention = ReplayRetention(max_turns=2)
        first = [{"name": "a.png"}]
        second = [{"name": "b.png"}]
        retention.retain(first)
        retention.retain(second)

        assert first == [{"name": "a.png"}]
        assert second == [{"name": "b.png"}]

    def test_eviction_clears_the_oldest_in_place(self) -> None:
        from app.components.frontend.controls.chat.attachments_ui import (
            ReplayRetention,
        )

        retention = ReplayRetention(max_turns=2)
        first = [{"name": "a.png"}]
        retention.retain(first)
        retention.retain([{"name": "b.png"}])
        retention.retain([{"name": "c.png"}])

        assert first == []  # the closure holding this list now sends no images

    def test_empty_turns_are_not_retained(self) -> None:
        from app.components.frontend.controls.chat.attachments_ui import (
            ReplayRetention,
        )

        retention = ReplayRetention(max_turns=1)
        kept = [{"name": "a.png"}]
        retention.retain(kept)
        retention.retain([])  # a text-only turn must not evict real images

        assert kept == [{"name": "a.png"}]


class TestAttachmentChips:
    """A staged image's chip shows the image itself - a thumbnail you
    can click for full size - not just a filename."""

    @staticmethod
    def _chip():
        from app.components.frontend.controls.chat.panel import ChatPanel

        panel = ChatPanel()
        return panel._attachment_chip(
            {"media_type": "image/png", "data_b64": "aGk=", "name": "order.png"}
        )

    def test_the_chip_carries_a_thumbnail_of_the_actual_image(self) -> None:
        import flet as ft

        from tests.components.frontend._tree import walk

        chip = self._chip()
        images = [n for n in walk(chip) if isinstance(n, ft.Image)]

        assert len(images) == 1
        assert images[0].src_base64 == "aGk="

    def test_the_thumbnail_is_clickable_for_full_size(self) -> None:
        from tests.components.frontend._tree import walk

        chip = self._chip()
        clickable = [
            n
            for n in walk(chip)
            if getattr(n, "tooltip", None) == "View full size"
            and getattr(n, "on_click", None) is not None
        ]

        assert len(clickable) == 1

    def test_the_name_and_remove_control_remain(self) -> None:
        from tests.components.frontend._tree import walk

        chip = self._chip()
        assert "order.png" in rendered(chip)
        assert any(
            getattr(n, "tooltip", None) == "Remove" for n in walk(chip)
        )
