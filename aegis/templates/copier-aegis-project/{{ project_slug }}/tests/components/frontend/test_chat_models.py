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
        {"model_id": "gpt-4o", "vendor": "OpenAI", "family": "gpt-4o",
         "released_on": "2024-05-13"},
        {"model_id": "claude-s4", "vendor": "Anthropic", "family": "claude-4",
         "released_on": "2025-05-22"},
        {"model_id": "gpt-4o-mini", "vendor": "OpenAI", "family": "gpt-4o",
         "released_on": "2024-07-18"},
        {"model_id": "mystery", "vendor": None, "family": None,
         "released_on": None},
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
