"""Tests for LLM catalog context functionality."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from app.services.ai.llm_catalog_context import (
    FEATURED_VENDORS,
    TOP_MODELS_PER_VENDOR,
    FlagshipModel,
    LLMCatalogContext,
    _extract_date_from_model_id,
    _is_alias_model,
    get_llm_catalog_context,
)
from app.services.ai.models.llm import (
    Direction,
    LargeLanguageModel,
    LLMDeployment,
    LLMModality,
    LLMPrice,
    LLMVendor,
    Modality,
)

# =============================================================================
# Unit Tests for Helper Functions
# =============================================================================


class TestExtractDateFromModelId:
    """Tests for _extract_date_from_model_id helper function."""

    def test_extracts_date_from_claude_model(self) -> None:
        """Should extract date from claude-opus-4-5-20251101 format."""
        result = _extract_date_from_model_id("claude-opus-4-5-20251101")
        assert result == datetime(2025, 11, 1, tzinfo=UTC)

    def test_extracts_date_from_sonnet_model(self) -> None:
        """Should extract date from claude-sonnet-4-5-20250929 format."""
        result = _extract_date_from_model_id("claude-sonnet-4-5-20250929")
        assert result == datetime(2025, 9, 29, tzinfo=UTC)

    def test_extracts_date_from_older_claude_format(self) -> None:
        """Should extract date from claude-3-5-sonnet-20241022 format."""
        result = _extract_date_from_model_id("claude-3-5-sonnet-20241022")
        assert result == datetime(2024, 10, 22, tzinfo=UTC)

    def test_extracts_date_from_gpt_model(self) -> None:
        """Should extract date from gpt-4-turbo-20240409 format."""
        result = _extract_date_from_model_id("gpt-4-turbo-20240409")
        assert result == datetime(2024, 4, 9, tzinfo=UTC)

    def test_returns_none_for_model_without_date(self) -> None:
        """Should return None for models without YYYYMMDD date."""
        result = _extract_date_from_model_id("claude-opus-4-5")
        assert result is None

    def test_returns_none_for_latest_suffix(self) -> None:
        """Should return None for models with -latest suffix (no date)."""
        result = _extract_date_from_model_id("claude-3-5-sonnet-latest")
        assert result is None

    def test_returns_none_for_hyphenated_date_format(self) -> None:
        """Should return None for YYYY-MM-DD format (not YYYYMMDD)."""
        result = _extract_date_from_model_id("gpt-4o-2024-08-06")
        assert result is None

    def test_returns_none_for_invalid_date(self) -> None:
        """Should return None for invalid dates like 20241399."""
        result = _extract_date_from_model_id("model-20241399")
        assert result is None

    def test_returns_none_for_short_number_sequence(self) -> None:
        """Should return None for numbers shorter than 8 digits."""
        result = _extract_date_from_model_id("gpt-4-32k")
        assert result is None

    def test_extracts_first_valid_date_only(self) -> None:
        """Should extract the first 8-digit date found."""
        result = _extract_date_from_model_id("model-20250101-v2-20251231")
        assert result == datetime(2025, 1, 1, tzinfo=UTC)


class TestIsAliasModel:
    """Tests for _is_alias_model helper function."""

    def test_detects_latest_suffix(self) -> None:
        """Should detect -latest suffix as alias."""
        assert _is_alias_model("claude-3-5-sonnet-latest") is True
        assert _is_alias_model("gpt-4-latest") is True

    def test_detects_colon_latest_suffix(self) -> None:
        """Should detect :latest suffix as alias."""
        assert _is_alias_model("model:latest") is True

    def test_dated_models_are_not_aliases(self) -> None:
        """Should not flag dated models as aliases."""
        assert _is_alias_model("claude-opus-4-5-20251101") is False
        assert _is_alias_model("gpt-4-turbo-20240409") is False

    def test_short_names_are_not_aliases(self) -> None:
        """Should not flag short names without -latest as aliases."""
        # These are technically aliases but we only filter -latest
        assert _is_alias_model("claude-opus-4-5") is False
        assert _is_alias_model("gpt-4o") is False

    def test_empty_string(self) -> None:
        """Should handle empty string."""
        assert _is_alias_model("") is False


# =============================================================================
# Integration Tests with Database
# =============================================================================


@pytest.fixture
def catalog_db_engine(engine: Engine) -> Engine:
    """The root conftest's schema-attached engine.

    A bare local ``create_engine`` cannot ``create_all`` this project's
    metadata: the root conftest imports every service's models, so tables
    live in named schemas (finance, scheduler, ...) that only the shared
    engine attaches in-memory databases for.
    """
    return engine


@pytest.fixture
def catalog_session(db_session: Session) -> Session:
    """The root conftest's transactional session (rolled back per test),
    riding the same connection as ``catalog_db_engine``."""
    return db_session


@pytest.fixture
def anthropic_vendor(catalog_session: Session) -> LLMVendor:
    """Create Anthropic vendor."""
    vendor = LLMVendor(
        name="anthropic",
        description="Anthropic API",
        color="#D4A27F",
        api_base="https://api.anthropic.com/v1",
        auth_method="api-key",
    )
    catalog_session.add(vendor)
    catalog_session.commit()
    catalog_session.refresh(vendor)
    return vendor


@pytest.fixture
def openai_vendor(catalog_session: Session) -> LLMVendor:
    """Create OpenAI vendor."""
    vendor = LLMVendor(
        name="openai",
        description="OpenAI API",
        color="#10A37F",
        api_base="https://api.openai.com/v1",
        auth_method="api-key",
    )
    catalog_session.add(vendor)
    catalog_session.commit()
    catalog_session.refresh(vendor)
    return vendor


@pytest.fixture
def anthropic_models(
    catalog_session: Session, anthropic_vendor: LLMVendor
) -> list[LargeLanguageModel]:
    """Create multiple Anthropic models with varying dates."""
    models = [
        LargeLanguageModel(
            model_id="claude-opus-4-5-20251101",
            title="Claude Opus 4.5",
            context_window=200000,
            llm_vendor_id=anthropic_vendor.id,
        ),
        LargeLanguageModel(
            model_id="claude-sonnet-4-5-20250929",
            title="Claude Sonnet 4.5",
            context_window=200000,
            llm_vendor_id=anthropic_vendor.id,
        ),
        LargeLanguageModel(
            model_id="claude-3-5-sonnet-20241022",
            title="Claude 3.5 Sonnet",
            context_window=200000,
            llm_vendor_id=anthropic_vendor.id,
        ),
        LargeLanguageModel(
            model_id="claude-3-5-sonnet-latest",  # Alias - should be filtered
            title="Claude 3.5 Sonnet Latest",
            context_window=200000,
            llm_vendor_id=anthropic_vendor.id,
        ),
        LargeLanguageModel(
            model_id="claude-3-haiku-20240307",
            title="Claude 3 Haiku",
            context_window=200000,
            llm_vendor_id=anthropic_vendor.id,
        ),
    ]
    for model in models:
        catalog_session.add(model)
    catalog_session.commit()
    for model in models:
        catalog_session.refresh(model)
    return models


@pytest.fixture
def openai_models_with_released_on(
    catalog_session: Session, openai_vendor: LLMVendor
) -> list[LargeLanguageModel]:
    """Create OpenAI models with released_on dates set."""
    models = [
        LargeLanguageModel(
            model_id="gpt-4o",
            title="GPT-4o",
            context_window=128000,
            llm_vendor_id=openai_vendor.id,
            released_on=datetime(2024, 5, 13, tzinfo=UTC),
        ),
        LargeLanguageModel(
            model_id="gpt-4-turbo",
            title="GPT-4 Turbo",
            context_window=128000,
            llm_vendor_id=openai_vendor.id,
            released_on=datetime(2024, 4, 9, tzinfo=UTC),
        ),
        LargeLanguageModel(
            model_id="gpt-3.5-turbo",
            title="GPT-3.5 Turbo",
            context_window=16385,
            llm_vendor_id=openai_vendor.id,
            released_on=datetime(2023, 3, 1, tzinfo=UTC),
        ),
    ]
    for model in models:
        catalog_session.add(model)
    catalog_session.commit()
    for model in models:
        catalog_session.refresh(model)
    return models


class TestLLMCatalogContextBuild:
    """Tests for LLMCatalogContext.build() method."""

    def test_returns_empty_context_with_no_vendors(
        self, catalog_session: Session
    ) -> None:
        """Should return empty context when no vendors exist."""
        context = LLMCatalogContext.build(catalog_session)
        assert context.flagships == []

    def test_returns_empty_context_with_no_models(
        self, catalog_session: Session, anthropic_vendor: LLMVendor
    ) -> None:
        """Should return empty context when vendor has no models."""
        context = LLMCatalogContext.build(catalog_session)
        assert context.flagships == []

    def test_sorts_by_date_extracted_from_model_id(
        self,
        catalog_session: Session,
        anthropic_vendor: LLMVendor,
        anthropic_models: list[LargeLanguageModel],
    ) -> None:
        """Should sort models by date extracted from model_id."""
        context = LLMCatalogContext.build(catalog_session)

        # Should have TOP_MODELS_PER_VENDOR models (excluding -latest alias)
        anthropic_flagships = [f for f in context.flagships if f.vendor == "anthropic"]
        assert len(anthropic_flagships) == TOP_MODELS_PER_VENDOR

        # First model should be newest (claude-opus-4-5-20251101)
        assert anthropic_flagships[0].model_id == "claude-opus-4-5-20251101"
        assert anthropic_flagships[0].title == "Claude Opus 4.5"

        # Second should be claude-sonnet-4-5-20250929
        assert anthropic_flagships[1].model_id == "claude-sonnet-4-5-20250929"

        # Third should be claude-3-5-sonnet-20241022
        assert anthropic_flagships[2].model_id == "claude-3-5-sonnet-20241022"

    def test_filters_out_latest_aliases(
        self,
        catalog_session: Session,
        anthropic_vendor: LLMVendor,
        anthropic_models: list[LargeLanguageModel],
    ) -> None:
        """Should filter out models ending in -latest."""
        context = LLMCatalogContext.build(catalog_session)

        # Should not include claude-3-5-sonnet-latest
        model_ids = [f.model_id for f in context.flagships]
        assert "claude-3-5-sonnet-latest" not in model_ids

    def test_prefers_released_on_over_extracted_date(
        self,
        catalog_session: Session,
        openai_vendor: LLMVendor,
        openai_models_with_released_on: list[LargeLanguageModel],
    ) -> None:
        """Should use released_on date when available."""
        context = LLMCatalogContext.build(catalog_session)

        openai_flagships = [f for f in context.flagships if f.vendor == "openai"]
        assert len(openai_flagships) == 3

        # Should be sorted by released_on (gpt-4o is newest at 2024-05-13)
        assert openai_flagships[0].model_id == "gpt-4o"
        assert openai_flagships[1].model_id == "gpt-4-turbo"
        assert openai_flagships[2].model_id == "gpt-3.5-turbo"

    def test_limits_to_top_n_per_vendor(
        self, catalog_session: Session, anthropic_vendor: LLMVendor
    ) -> None:
        """Should only return TOP_MODELS_PER_VENDOR models per vendor."""
        # Create more models than the limit
        for i in range(10):
            model = LargeLanguageModel(
                model_id=f"claude-test-{20250101 + i:08d}",
                title=f"Claude Test {i}",
                context_window=100000,
                llm_vendor_id=anthropic_vendor.id,
            )
            catalog_session.add(model)
        catalog_session.commit()

        context = LLMCatalogContext.build(catalog_session)
        anthropic_flagships = [f for f in context.flagships if f.vendor == "anthropic"]

        assert len(anthropic_flagships) == TOP_MODELS_PER_VENDOR


class TestLLMCatalogContextWithRelatedData:
    """Tests for LLMCatalogContext with prices, deployments, and modalities."""

    def test_includes_pricing_data(
        self,
        catalog_session: Session,
        openai_vendor: LLMVendor,
    ) -> None:
        """Should include pricing information in flagship models."""
        # Create model
        model = LargeLanguageModel(
            model_id="gpt-4o-20240513",
            title="GPT-4o",
            context_window=128000,
            llm_vendor_id=openai_vendor.id,
        )
        catalog_session.add(model)
        catalog_session.commit()
        catalog_session.refresh(model)

        # Create price
        price = LLMPrice(
            llm_id=model.id,
            llm_vendor_id=openai_vendor.id,
            input_cost_per_token=0.000005,  # $5 per 1M
            output_cost_per_token=0.000015,  # $15 per 1M
            effective_date=datetime.now(),
        )
        catalog_session.add(price)
        catalog_session.commit()

        context = LLMCatalogContext.build(catalog_session)
        flagship = context.flagships[0]

        assert flagship.input_cost_per_m == 5.0
        assert flagship.output_cost_per_m == 15.0

    def test_includes_deployment_capabilities(
        self,
        catalog_session: Session,
        openai_vendor: LLMVendor,
    ) -> None:
        """Should include deployment capabilities in flagship models."""
        # Create model
        model = LargeLanguageModel(
            model_id="gpt-4o-20240513",
            title="GPT-4o",
            context_window=128000,
            llm_vendor_id=openai_vendor.id,
        )
        catalog_session.add(model)
        catalog_session.commit()
        catalog_session.refresh(model)

        # Create deployment
        deployment = LLMDeployment(
            llm_id=model.id,
            llm_vendor_id=openai_vendor.id,
            function_calling=True,
            structured_output=True,
        )
        catalog_session.add(deployment)
        catalog_session.commit()

        context = LLMCatalogContext.build(catalog_session)
        flagship = context.flagships[0]

        assert flagship.function_calling is True
        assert flagship.structured_output is True

    def test_includes_vision_capability(
        self,
        catalog_session: Session,
        openai_vendor: LLMVendor,
    ) -> None:
        """Should detect vision capability from modalities."""
        # Create model
        model = LargeLanguageModel(
            model_id="gpt-4o-20240513",
            title="GPT-4o",
            context_window=128000,
            llm_vendor_id=openai_vendor.id,
        )
        catalog_session.add(model)
        catalog_session.commit()
        catalog_session.refresh(model)

        # Create image input modality
        modality = LLMModality(
            llm_id=model.id,
            modality=Modality.IMAGE,
            direction=Direction.INPUT,
        )
        catalog_session.add(modality)
        catalog_session.commit()

        context = LLMCatalogContext.build(catalog_session)
        flagship = context.flagships[0]

        assert flagship.vision is True


class TestFormatForPrompt:
    """Tests for LLMCatalogContext.format_for_prompt() method."""

    def test_returns_empty_string_for_empty_context(self) -> None:
        """Should return empty string when no flagships."""
        context = LLMCatalogContext([])
        assert context.format_for_prompt() == ""

    def test_formats_basic_model_info(self) -> None:
        """Should format model with basic info."""
        flagship = FlagshipModel(
            vendor="openai",
            model_id="gpt-4o",
            title="GPT-4o",
            input_cost_per_m=5.0,
            output_cost_per_m=15.0,
            context_window=128000,
            function_calling=True,
            vision=True,
            structured_output=True,
        )
        context = LLMCatalogContext([flagship])
        output = context.format_for_prompt()

        assert "LLM Catalog (Top Models by Vendor):" in output
        assert "Openai:" in output
        assert "GPT-4o" in output
        assert "$5.00/$15.00/M" in output
        assert "128K ctx" in output
        assert "functions" in output
        assert "vision" in output
        assert "structured" in output

    def test_formats_million_context_window(self) -> None:
        """Should format 1M+ context windows as 'M'."""
        flagship = FlagshipModel(
            vendor="anthropic",
            model_id="claude-opus",
            title="Claude Opus",
            input_cost_per_m=15.0,
            output_cost_per_m=75.0,
            context_window=1000000,
            function_calling=True,
            vision=False,
            structured_output=False,
        )
        context = LLMCatalogContext([flagship])
        output = context.format_for_prompt()

        assert "1M ctx" in output

    def test_formats_basic_capabilities(self) -> None:
        """Should show 'basic' when no capabilities."""
        flagship = FlagshipModel(
            vendor="test",
            model_id="test-model",
            title="Test Model",
            input_cost_per_m=1.0,
            output_cost_per_m=2.0,
            context_window=4096,
            function_calling=False,
            vision=False,
            structured_output=False,
        )
        context = LLMCatalogContext([flagship])
        output = context.format_for_prompt()

        assert "basic" in output

    def test_groups_by_vendor(self) -> None:
        """Should group models by vendor."""
        flagships = [
            FlagshipModel(
                vendor="openai",
                model_id="gpt-4o",
                title="GPT-4o",
                input_cost_per_m=5.0,
                output_cost_per_m=15.0,
                context_window=128000,
                function_calling=True,
                vision=True,
                structured_output=True,
            ),
            FlagshipModel(
                vendor="openai",
                model_id="gpt-4-turbo",
                title="GPT-4 Turbo",
                input_cost_per_m=10.0,
                output_cost_per_m=30.0,
                context_window=128000,
                function_calling=True,
                vision=True,
                structured_output=False,
            ),
            FlagshipModel(
                vendor="anthropic",
                model_id="claude-opus",
                title="Claude Opus",
                input_cost_per_m=15.0,
                output_cost_per_m=75.0,
                context_window=200000,
                function_calling=True,
                vision=True,
                structured_output=False,
            ),
        ]
        context = LLMCatalogContext(flagships)
        output = context.format_for_prompt()

        # Check vendor headers appear
        assert "Openai:" in output
        assert "Anthropic:" in output

        # Check models are listed
        assert "GPT-4o" in output
        assert "GPT-4 Turbo" in output
        assert "Claude Opus" in output


class TestGetLLMCatalogContext:
    """Tests for get_llm_catalog_context convenience function."""

    def test_returns_formatted_string(
        self,
        catalog_session: Session,
        openai_vendor: LLMVendor,
        openai_models_with_released_on: list[LargeLanguageModel],
    ) -> None:
        """Should return formatted string from convenience function."""
        result = get_llm_catalog_context(catalog_session)

        assert isinstance(result, str)
        assert "LLM Catalog" in result
        assert "Openai:" in result

    def test_returns_empty_for_no_data(self, catalog_session: Session) -> None:
        """Should return empty string when no data."""
        result = get_llm_catalog_context(catalog_session)
        assert result == ""


class TestFeaturedVendors:
    """Tests for FEATURED_VENDORS configuration."""

    def test_includes_major_providers(self) -> None:
        """Should include all major AI providers."""
        assert "openai" in FEATURED_VENDORS
        assert "anthropic" in FEATURED_VENDORS
        assert "google" in FEATURED_VENDORS
        assert "mistral" in FEATURED_VENDORS
        assert "deepseek" in FEATURED_VENDORS

    def test_vendor_order_is_significant(self) -> None:
        """Major providers should be listed first."""
        # OpenAI and Anthropic should be near the top
        assert FEATURED_VENDORS.index("openai") < 3
        assert FEATURED_VENDORS.index("anthropic") < 3
