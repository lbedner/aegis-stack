"""Durable readings: what a vision turn extracted, kept past the image.

Image bytes ride one turn by design; the READING must not. The
``record_reading`` tool stages a validated extraction during the model
call, the turn's finalize merges it into the USER's store, and every
later turn gets it re-injected as context - so "list the items again"
works forever without re-attaching anything, in any thread.
"""

import pytest

from app.services.ai.domains.chat.readings import (
    Reading,
    ReadingItem,
    format_readings,
    merge_staged_readings,
    reading_stage,
    record_reading,
)

_ITEMS = [
    {"label": "Disposable Clear Cups 18oz 28ct", "quantity": 4, "amount_cents": 299},
    {"label": "Tide Free & Gentle 105oz", "amount_cents": 1599},
    {"label": "Elmer's Glue Sticks 2pk", "amount_cents": 50, "note": "school"},
]


class TestRecordReading:
    @pytest.mark.asyncio
    async def test_a_reading_stages_inside_a_turn(self) -> None:
        with reading_stage() as staged:
            result = await record_reading(
                title="Target order 8/27", items=_ITEMS, kind="receipt"
            )

        assert result["recorded"] == 3
        assert len(staged) == 1
        assert staged[0]["title"] == "Target order 8/27"
        assert staged[0]["items"][0]["quantity"] == 4

    @pytest.mark.asyncio
    async def test_recording_outside_a_turn_reports_not_saves(self) -> None:
        result = await record_reading(title="x", items=_ITEMS)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_bad_items_are_rejected_with_a_correctable_error(self) -> None:
        with reading_stage() as staged:
            result = await record_reading(
                title="x", items=[{"label": "", "amount_cents": -5}]
            )

        assert "error" in result
        assert staged == []

    @pytest.mark.asyncio
    async def test_empty_items_are_rejected(self) -> None:
        with reading_stage() as staged:
            result = await record_reading(title="x", items=[])

        assert "error" in result
        assert staged == []


class TestMergeAndFormat:
    @pytest.mark.asyncio
    async def test_staged_readings_merge_into_the_user_store(self) -> None:
        from app.services.ai.domains.chat.readings import user_readings

        reading = Reading(
            title="Target order", items=[ReadingItem(**i) for i in _ITEMS]
        ).model_dump()

        await merge_staged_readings("merge-u1", [reading])
        await merge_staged_readings(
            "merge-u1", []
        )  # a readingless turn changes nothing

        stored = await user_readings("merge-u1")
        assert len(stored) == 1
        assert stored[0]["title"] == "Target order"

    def test_format_renders_every_item_with_money_and_counts(self) -> None:
        reading = Reading(
            title="Target order", items=[ReadingItem(**i) for i in _ITEMS]
        ).model_dump()

        block = format_readings([reading])

        assert block is not None
        assert "Target order" in block
        assert "Disposable Clear Cups 18oz 28ct" in block
        assert "x4" in block
        assert "$2.99" in block
        assert "$15.99" in block
        assert "school" in block

    def test_groups_survive_recording_and_render(self) -> None:
        """Source structure (a shipment, a sub-receipt, a page) must not
        flatten away - which group an item belongs to is exactly what
        maps it to the right charge later."""
        reading = Reading(
            title="Target order",
            items=[
                ReadingItem(
                    label="Markers", amount_cents=399, group="Arriving Thu, Aug 27"
                ),
                ReadingItem(
                    label="Tide", amount_cents=1599, group="Arriving Fri, Aug 28"
                ),
            ],
        ).model_dump()

        block = format_readings([reading])

        assert block is not None
        assert "Arriving Thu, Aug 27" in block
        assert "Arriving Fri, Aug 28" in block

    def test_no_readings_formats_to_none(self) -> None:
        assert format_readings(None) is None
        assert format_readings([]) is None
