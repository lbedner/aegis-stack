"""The chat composer's model selector: pure display/grouping helpers."""

from app.components.frontend.controls.chat.models import (
    family_display_name,
    group_models,
    model_label,
    newest_first,
)


class TestModelLabel:
    def test_shows_the_resolved_model_clipped(self) -> None:
        assert model_label({"model": "qwen3.8:27b-mlx"}) == "qwen3.8:27b-mlx"
        long = {"model": "anthropic/claude-sonnet-4-5-20250929-extended"}
        assert len(model_label(long)) == 24
        assert model_label(long).endswith("...")

    def test_placeholder_when_nothing_resolved(self) -> None:
        assert model_label(None) == "model"
        assert model_label({}) == "model"


class TestNewestFirst:
    def test_sorts_by_release_date_descending_undated_last(self) -> None:
        models = [
            {"model_id": "old", "released_on": "2024-01-01"},
            {"model_id": "undated", "released_on": None},
            {"model_id": "new", "released_on": "2026-06-01"},
        ]

        ordered = newest_first(models)

        assert [m["model_id"] for m in ordered] == ["new", "old", "undated"]


class TestGroupModels:
    _models = [
        {
            "model_id": "gpt-4o",
            "vendor": "OpenAI",
            "family": "gpt-4o",
            "released_on": "2024-05-13",
        },
        {
            "model_id": "claude-s4",
            "vendor": "Anthropic",
            "family": "claude-4",
            "released_on": "2025-05-22",
        },
        {
            "model_id": "gpt-4o-mini",
            "vendor": "OpenAI",
            "family": "gpt-4o",
            "released_on": "2024-07-18",
        },
        {"model_id": "mystery", "vendor": None, "family": None, "released_on": None},
    ]

    def test_groups_by_vendor_newest_first_within(self) -> None:
        grouped = group_models(self._models, by="vendor")

        assert [name for name, _rows in grouped] == [
            "Anthropic",
            "OpenAI",
            "Other",
        ]
        openai = dict(grouped)["OpenAI"]
        assert [m["model_id"] for m in openai] == ["gpt-4o-mini", "gpt-4o"]

    def test_groups_by_family_with_display_names(self) -> None:
        grouped = group_models(self._models, by="family")

        names = [name for name, _rows in grouped]
        assert "Claude 4" in names
        assert "Gpt 4o" in names
        assert names[-1] == "Other"


class TestFamilyDisplayName:
    def test_prettifies_slugs(self) -> None:
        assert family_display_name("claude-3.5") == "Claude 3.5"
        assert family_display_name("llama-3.2") == "Llama 3.2"
        assert family_display_name(None) == "Other"


class TestFormatContextWindow:
    def test_compact_units(self) -> None:
        from app.components.frontend.controls.chat.models import format_context_window

        assert format_context_window(8_192) == "8k"
        assert format_context_window(128_000) == "128k"
        assert format_context_window(200_000) == "200k"
        assert format_context_window(1_048_576) == "1M"
        assert format_context_window(2_000_000) == "2M"

    def test_unknown_is_blank(self) -> None:
        from app.components.frontend.controls.chat.models import format_context_window

        assert format_context_window(0) == ""
        assert format_context_window(None) == ""


class TestFormatPrice:
    def test_in_and_out_per_million(self) -> None:
        from app.components.frontend.controls.chat.models import format_price

        assert format_price(1.25, 10.0) == "$1.25 / $10"
        assert format_price(3.0, 15.0) == "$3 / $15"

    def test_partial_or_missing_is_blank_or_single(self) -> None:
        from app.components.frontend.controls.chat.models import format_price

        assert format_price(None, None) == ""
        assert format_price(0.5, None) == "$0.50"


class TestFilterModels:
    def test_matches_id_title_and_vendor_case_insensitive(self) -> None:
        from app.components.frontend.controls.chat.models import filter_models

        models = [
            {"model_id": "gpt-5.6-terra", "title": "GPT-5.6 Terra", "vendor": "openai"},
            {"model_id": "claude-opus-5", "title": "Opus 5", "vendor": "anthropic"},
        ]
        assert [m["model_id"] for m in filter_models(models, "opus")] == [
            "claude-opus-5"
        ]
        assert [m["model_id"] for m in filter_models(models, "OPENAI")] == [
            "gpt-5.6-terra"
        ]
        assert filter_models(models, "") == models


class TestDisplayTitle:
    def test_strips_the_vendors_own_prefix_under_its_section(self) -> None:
        from app.components.frontend.controls.chat.models import display_title

        model = {"title": "OpenAI: GPT-5.6 Luna", "vendor": "openai"}
        assert display_title(model, under_vendor="openai") == "GPT-5.6 Luna"

    def test_keeps_the_prefix_in_flat_views(self) -> None:
        from app.components.frontend.controls.chat.models import display_title

        model = {"title": "OpenAI: GPT-5.6 Luna", "vendor": "openai"}
        assert display_title(model, under_vendor=None) == "OpenAI: GPT-5.6 Luna"

    def test_leaves_unprefixed_titles_alone(self) -> None:
        from app.components.frontend.controls.chat.models import display_title

        model = {"title": "Gpt Oss:20B", "vendor": "ollama", "model_id": "gpt-oss:20b"}
        assert display_title(model, under_vendor="ollama") == "Gpt Oss:20B"


class TestLabForModel:
    """The lab is DATA now - resolved from the model registry at sync
    time and carried on the row - not a prefix table that goes stale the
    week a lab ships under a new product name."""

    def test_it_reads_the_resolved_lab(self) -> None:
        from app.components.frontend.controls.chat.models import lab_for_model

        model = {"model_id": "muse-glimmer:30b-mlx", "lab": "Meta Inc."}
        assert lab_for_model(model) == "Meta Inc."

    def test_an_unresolved_model_has_no_lab(self) -> None:
        from app.components.frontend.controls.chat.models import lab_for_model

        assert lab_for_model({"model_id": "my-private-merge"}) is None
        assert lab_for_model({"model_id": "x", "lab": None}) is None


class TestModelPickerDialog:
    """Dialog behavior: picking keeps it open (compare, then leave), and
    the barrier is dismissable - clicking outside closes it."""

    @staticmethod
    def _dialog():
        from app.components.frontend.controls.chat.model_picker import (
            ModelPickerDialog,
        )

        async def _noop(*_args: object) -> None:
            return None

        return ModelPickerDialog(
            models=[
                {"model_id": "a-1", "title": "A One", "vendor": "acme"},
                {"model_id": "b-2", "title": "B Two", "vendor": "acme"},
            ],
            active_id="a-1",
            on_pick=_noop,
            on_close=_noop,
        )

    def test_outside_click_can_dismiss(self) -> None:
        assert self._dialog().modal is False

    def test_set_active_moves_the_marker_without_closing(self) -> None:
        dialog = self._dialog()
        before = dialog._list_host.content

        dialog.set_active("b-2")

        assert dialog._active_id == "b-2"
        assert dialog._list_host.content is not before  # rows re-rendered
