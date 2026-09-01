"""Tests for LLM service business logic."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from app.services.ai.domains.llm.llm_service import (
    get_current_config,
    get_model_info,
    list_modalities,
    list_models,
    list_vendors,
    set_active_model,
)
from app.services.ai.models.llm import (
    Direction,
    LargeLanguageModel,
    LLMModality,
    LLMOrg,
    LLMPrice,
    Modality,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def llm_db_engine(engine: Engine) -> Engine:
    """The root conftest's schema-attached engine.

    A bare local ``create_engine`` cannot ``create_all`` this project's
    metadata: the root conftest imports every service's models, so tables
    live in named schemas (finance, scheduler, ...) that only the shared
    engine attaches in-memory databases for.
    """
    return engine


@pytest.fixture
def llm_session(db_session: Session) -> Session:
    """The root conftest's transactional session (rolled back per test),
    riding the same connection as ``llm_db_engine``."""
    return db_session


@pytest.fixture
def anthropic_vendor(llm_session: Session) -> LLMOrg:
    """Create Anthropic vendor."""
    vendor = LLMOrg(
        slug="anthropic",
        name="anthropic",
        description="Anthropic API",
        color="#D4A27F",
        api_base="https://api.anthropic.com/v1",
        auth_method="api-key",
    )
    llm_session.add(vendor)
    llm_session.commit()
    llm_session.refresh(vendor)
    return vendor


@pytest.fixture
def openai_vendor(llm_session: Session) -> LLMOrg:
    """Create OpenAI vendor."""
    vendor = LLMOrg(
        slug="openai",
        name="openai",
        description="OpenAI API",
        color="#10A37F",
        api_base="https://api.openai.com/v1",
        auth_method="api-key",
    )
    llm_session.add(vendor)
    llm_session.commit()
    llm_session.refresh(vendor)
    return vendor


@pytest.fixture
def sample_models(
    llm_session: Session, anthropic_vendor: LLMOrg, openai_vendor: LLMOrg
) -> list[LargeLanguageModel]:
    """Create sample LLM models for testing."""
    models = [
        LargeLanguageModel(
            model_id="claude-sonnet-4-20250514",
            title="Claude Sonnet 4",
            description="Fast, intelligent model",
            context_window=200000,
            streamable=True,
            enabled=True,
            served_by_org_id=anthropic_vendor.id,
            released_on=datetime(2025, 5, 14, tzinfo=UTC),
        ),
        LargeLanguageModel(
            model_id="claude-opus-4-20250514",
            title="Claude Opus 4",
            description="Most powerful model",
            context_window=200000,
            streamable=True,
            enabled=True,
            served_by_org_id=anthropic_vendor.id,
            released_on=datetime(2025, 5, 14, tzinfo=UTC),
        ),
        LargeLanguageModel(
            model_id="gpt-4o",
            title="GPT-4o",
            description="OpenAI's multimodal model",
            context_window=128000,
            streamable=True,
            enabled=True,
            served_by_org_id=openai_vendor.id,
            released_on=datetime(2024, 5, 13, tzinfo=UTC),
        ),
        LargeLanguageModel(
            model_id="gpt-3.5-turbo",
            title="GPT-3.5 Turbo",
            description="Fast and affordable",
            context_window=16385,
            streamable=True,
            enabled=False,  # Disabled model
            served_by_org_id=openai_vendor.id,
        ),
    ]
    for model in models:
        llm_session.add(model)
    llm_session.commit()
    for model in models:
        llm_session.refresh(model)
    return models


@pytest.fixture
def sample_prices(
    llm_session: Session,
    sample_models: list[LargeLanguageModel],
    anthropic_vendor: LLMOrg,
    openai_vendor: LLMOrg,
) -> list[LLMPrice]:
    """Create sample prices for models."""
    prices = []
    # Claude Sonnet 4 pricing
    prices.append(
        LLMPrice(
            llm_id=sample_models[0].id,
            org_id=anthropic_vendor.id,
            input_cost_per_token=0.000003,  # $3 per 1M
            output_cost_per_token=0.000015,  # $15 per 1M
            effective_date=datetime.now(UTC),
        )
    )
    # Claude Opus 4 pricing
    prices.append(
        LLMPrice(
            llm_id=sample_models[1].id,
            org_id=anthropic_vendor.id,
            input_cost_per_token=0.000015,  # $15 per 1M
            output_cost_per_token=0.000075,  # $75 per 1M
            effective_date=datetime.now(UTC),
        )
    )
    # GPT-4o pricing
    prices.append(
        LLMPrice(
            llm_id=sample_models[2].id,
            org_id=openai_vendor.id,
            input_cost_per_token=0.000005,  # $5 per 1M
            output_cost_per_token=0.000015,  # $15 per 1M
            effective_date=datetime.now(UTC),
        )
    )
    for price in prices:
        llm_session.add(price)
    llm_session.commit()
    return prices


@pytest.fixture
def sample_modalities(
    llm_session: Session, sample_models: list[LargeLanguageModel]
) -> list[LLMModality]:
    """Create sample modalities for models."""
    modalities = []
    # Claude models - text input/output
    for model in sample_models[:2]:
        modalities.append(
            LLMModality(
                llm_id=model.id,
                modality=Modality.TEXT,
                direction=Direction.INPUT,
            )
        )
        modalities.append(
            LLMModality(
                llm_id=model.id,
                modality=Modality.TEXT,
                direction=Direction.OUTPUT,
            )
        )
    # GPT-4o - multimodal
    modalities.append(
        LLMModality(
            llm_id=sample_models[2].id,
            modality=Modality.TEXT,
            direction=Direction.INPUT,
        )
    )
    modalities.append(
        LLMModality(
            llm_id=sample_models[2].id,
            modality=Modality.IMAGE,
            direction=Direction.INPUT,
        )
    )
    modalities.append(
        LLMModality(
            llm_id=sample_models[2].id,
            modality=Modality.TEXT,
            direction=Direction.OUTPUT,
        )
    )
    for mod in modalities:
        llm_session.add(mod)
    llm_session.commit()
    return modalities


# =============================================================================
# Sync Function Tests
# =============================================================================


class TestListVendors:
    """Tests for list_vendors() function."""

    def test_empty_catalog(self, llm_session: Session, llm_db_engine: Engine) -> None:
        """Should return empty list when no vendors exist."""
        with patch("app.services.ai.domains.llm.llm_service.engine", llm_db_engine):
            results = list_vendors()
        assert results == []

    def test_vendors_with_model_counts(
        self,
        llm_session: Session,
        llm_db_engine: Engine,
        sample_models: list[LargeLanguageModel],
    ) -> None:
        """Should return vendors with correct model counts."""
        with patch("app.services.ai.domains.llm.llm_service.engine", llm_db_engine):
            results = list_vendors()

        assert len(results) == 2
        # Results should be sorted alphabetically
        assert results[0].name == "anthropic"
        assert results[0].model_count == 2
        assert results[1].name == "openai"
        assert results[1].model_count == 2

    def test_vendor_without_models(
        self, llm_session: Session, llm_db_engine: Engine, anthropic_vendor: LLMOrg
    ) -> None:
        """Should include vendors with zero models."""
        with patch("app.services.ai.domains.llm.llm_service.engine", llm_db_engine):
            results = list_vendors()

        assert len(results) == 1
        assert results[0].name == "anthropic"
        assert results[0].model_count == 0


class TestListModalities:
    """Tests for list_modalities() function."""

    def test_empty_catalog(self, llm_session: Session, llm_db_engine: Engine) -> None:
        """Should return empty list when no modalities exist."""
        with patch("app.services.ai.domains.llm.llm_service.engine", llm_db_engine):
            results = list_modalities()
        assert results == []

    def test_modalities_with_counts(
        self,
        llm_session: Session,
        llm_db_engine: Engine,
        sample_modalities: list[LLMModality],
    ) -> None:
        """Should return modalities with distinct model counts."""
        with patch("app.services.ai.domains.llm.llm_service.engine", llm_db_engine):
            results = list_modalities()

        assert len(results) == 2  # text and image
        modality_map = {r.modality: r.model_count for r in results}
        # Modalities are stored as enum str representation
        assert modality_map.get("Modality.IMAGE", modality_map.get("image")) == 1
        assert modality_map.get("Modality.TEXT", modality_map.get("text")) == 3


# =============================================================================
# Async Function Tests
# =============================================================================


@pytest.fixture
def mock_async_session(llm_session: Session):
    """Create a mock async session that wraps the sync session."""

    class MockAsyncResult:
        def __init__(self, sync_result):
            self._sync_result = sync_result

        def all(self):
            return list(self._sync_result)

        def first(self):
            return next(iter(self._sync_result), None)

    class MockAsyncSession:
        def __init__(self, session: Session):
            self._session = session

        async def exec(self, stmt):
            return MockAsyncResult(self._session.exec(stmt))

    @asynccontextmanager
    async def async_session_context() -> AsyncGenerator[MockAsyncSession]:
        yield MockAsyncSession(llm_session)

    return async_session_context


@pytest.mark.asyncio
class TestListModels:
    """Tests for list_models() async function."""

    async def test_empty_catalog(self, mock_async_session) -> None:
        """Should return empty list when no models exist."""
        with patch(
            "app.services.ai.domains.llm.catalog_queries.get_async_session",
            mock_async_session,
        ):
            results = await list_models(pattern="test")
        assert results == []

    async def test_pattern_filter_model_id(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
        sample_prices: list[LLMPrice],
    ) -> None:
        """Should filter by model_id pattern."""
        with patch(
            "app.services.ai.domains.llm.catalog_queries.get_async_session",
            mock_async_session,
        ):
            results = await list_models(pattern="claude")

        assert len(results) == 2
        assert all("claude" in r.model_id for r in results)

    async def test_pattern_filter_title(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
    ) -> None:
        """Should filter by title pattern."""
        with patch(
            "app.services.ai.domains.llm.catalog_queries.get_async_session",
            mock_async_session,
        ):
            results = await list_models(pattern="Opus")

        assert len(results) == 1
        assert results[0].model_id == "claude-opus-4-20250514"

    async def test_vendor_filter(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
    ) -> None:
        """Should filter by vendor name."""
        with patch(
            "app.services.ai.domains.llm.catalog_queries.get_async_session",
            mock_async_session,
        ):
            results = await list_models(vendor="openai")

        assert len(results) == 1  # Only gpt-4o (gpt-3.5-turbo is disabled)
        assert results[0].vendor == "openai"

    async def test_modality_filter(
        self,
        mock_async_session,
        sample_modalities: list[LLMModality],
    ) -> None:
        """Should filter by modality."""
        with patch(
            "app.services.ai.domains.llm.catalog_queries.get_async_session",
            mock_async_session,
        ):
            results = await list_models(modality=Modality.IMAGE)

        assert len(results) == 1
        assert results[0].model_id == "gpt-4o"

    async def test_limit_parameter(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
    ) -> None:
        """Should respect limit parameter."""
        with patch(
            "app.services.ai.domains.llm.catalog_queries.get_async_session",
            mock_async_session,
        ):
            results = await list_models(pattern="", limit=2, include_disabled=True)

        # Note: pattern="" won't match anything, need at least pattern/vendor/modality
        # Let's use vendor instead
        with patch(
            "app.services.ai.domains.llm.catalog_queries.get_async_session",
            mock_async_session,
        ):
            results = await list_models(vendor="anthropic", limit=1)

        assert len(results) == 1

    async def test_vendors_filter_caps_per_vendor_in_one_call(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
    ) -> None:
        """The picker's usable path: one query for ALL callable vendors,
        the limit applying per vendor so one large catalog cannot crowd
        the others out - it must not loop a session per vendor."""
        sessions = 0

        def counting_factory():
            nonlocal sessions
            sessions += 1
            return mock_async_session()

        with patch(
            "app.services.ai.domains.llm.catalog_queries.get_async_session",
            counting_factory,
        ):
            results = await list_models(vendors=["anthropic", "openai"], limit=1)

        by_vendor: dict[str, int] = {}
        for r in results:
            by_vendor[r.vendor] = by_vendor.get(r.vendor, 0) + 1
        assert by_vendor == {"anthropic": 1, "openai": 1}
        assert sessions == 1  # one session, not one per vendor

    async def test_vendors_filter_matches_exact_names(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
    ) -> None:
        """``vendors`` is a whitelist of exact names, not a pattern - an
        install keyed for "open" must not pull "openai" and "openrouter"."""
        with patch(
            "app.services.ai.domains.llm.catalog_queries.get_async_session",
            mock_async_session,
        ):
            results = await list_models(vendors=["open"])

        assert results == []

    async def test_include_disabled(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
    ) -> None:
        """Should include disabled models when flag is set."""
        with patch(
            "app.services.ai.domains.llm.catalog_queries.get_async_session",
            mock_async_session,
        ):
            results = await list_models(vendor="openai", include_disabled=True)

        assert len(results) == 2  # Both gpt-4o and gpt-3.5-turbo

    async def test_excludes_disabled_by_default(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
    ) -> None:
        """Should exclude disabled models by default."""
        with patch(
            "app.services.ai.domains.llm.catalog_queries.get_async_session",
            mock_async_session,
        ):
            results = await list_models(vendor="openai")

        assert len(results) == 1  # Only gpt-4o
        assert results[0].model_id == "gpt-4o"

    async def test_includes_pricing(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
        sample_prices: list[LLMPrice],
    ) -> None:
        """Should include pricing data when available."""
        with patch(
            "app.services.ai.domains.llm.catalog_queries.get_async_session",
            mock_async_session,
        ):
            results = await list_models(pattern="gpt-4o")

        assert len(results) == 1
        assert results[0].input_price == 5.0  # $5 per 1M
        assert results[0].output_price == 15.0  # $15 per 1M


@pytest.mark.asyncio
class TestGetCurrentConfig:
    """Tests for get_current_config() async function."""

    async def test_model_in_catalog(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
        sample_prices: list[LLMPrice],
        sample_modalities: list[LLMModality],
    ) -> None:
        """Should enrich config with catalog data when model exists."""
        mock_settings = MagicMock()
        mock_settings.AI_PROVIDER = "openai"
        mock_settings.AI_MODEL = "gpt-4o"
        mock_settings.AI_TEMPERATURE = 0.7
        mock_settings.AI_MAX_TOKENS = 4096

        with (
            patch(
                "app.services.ai.domains.llm.llm_service.get_async_session",
                mock_async_session,
            ),
            patch("app.services.ai.domains.llm.llm_service.settings", mock_settings),
        ):
            config = await get_current_config()

        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.context_window == 128000
        assert config.input_price == 5.0
        assert config.output_price == 15.0
        assert config.modalities is not None
        # Modalities may be formatted as enum repr or value
        assert any("text" in m.lower() for m in config.modalities)

    async def test_model_not_in_catalog(
        self,
        mock_async_session,
    ) -> None:
        """Should return basic config when model not in catalog."""
        mock_settings = MagicMock()
        mock_settings.AI_PROVIDER = "custom"
        mock_settings.AI_MODEL = "unknown-model"
        mock_settings.AI_TEMPERATURE = 0.5
        mock_settings.AI_MAX_TOKENS = 2000

        with (
            patch(
                "app.services.ai.domains.llm.llm_service.get_async_session",
                mock_async_session,
            ),
            patch("app.services.ai.domains.llm.llm_service.settings", mock_settings),
        ):
            config = await get_current_config()

        assert config.provider == "custom"
        assert config.model == "unknown-model"
        assert config.context_window is None
        assert config.input_price is None
        assert config.modalities is None


@pytest.mark.asyncio
class TestSetActiveModel:
    """Tests for set_active_model() async function."""

    async def test_model_exists(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
    ) -> None:
        """Should set model when it exists in catalog.

        ``read_env_file`` was removed from ``llm_service`` in the env-handling
        cleanup — the new implementation only writes via ``update_env_file``
        and auto-detects provider from the catalog vendor. Tests no longer
        need to seed prior env state.
        """
        with (
            patch(
                "app.services.ai.domains.llm.llm_service.get_async_session",
                mock_async_session,
            ),
            patch(
                "app.services.ai.domains.llm.llm_service.update_env_file"
            ) as mock_update,
        ):
            result = await set_active_model("claude-sonnet-4-20250514")

        assert result.success is True
        assert result.model_id == "claude-sonnet-4-20250514"
        assert result.vendor == "anthropic"
        mock_update.assert_called_once()
        call_args = mock_update.call_args[0][0]
        assert call_args["AI_MODEL"] == "claude-sonnet-4-20250514"

    async def test_model_not_found_without_force(
        self,
        mock_async_session,
    ) -> None:
        """Should fail when model not in catalog and force=False."""
        with patch(
            "app.services.ai.domains.llm.llm_service.get_async_session",
            mock_async_session,
        ):
            result = await set_active_model("nonexistent-model")

        assert result.success is False
        assert "not found in catalog" in result.message
        assert "Use --force" in result.message

    async def test_model_not_found_with_force(
        self,
        mock_async_session,
    ) -> None:
        """Should succeed with force=True even if model not in catalog."""
        with (
            patch(
                "app.services.ai.domains.llm.llm_service.get_async_session",
                mock_async_session,
            ),
            patch(
                "app.services.ai.domains.llm.llm_service.update_env_file"
            ) as mock_update,
        ):
            result = await set_active_model("custom-model", force=True)

        assert result.success is True
        assert result.model_id == "custom-model"
        mock_update.assert_called_once()

    async def test_provider_auto_switch(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
    ) -> None:
        """Should update provider when switching to different vendor."""
        with (
            patch(
                "app.services.ai.domains.llm.llm_service.get_async_session",
                mock_async_session,
            ),
            patch(
                "app.services.ai.domains.llm.llm_service.update_env_file"
            ) as mock_update,
        ):
            result = await set_active_model("gpt-4o")

        assert result.success is True
        assert result.provider_updated is True
        call_args = mock_update.call_args[0][0]
        assert call_args["AI_PROVIDER"] == "openai"

    @pytest.mark.skip(
        reason=(
            "``set_active_model`` no longer inspects the prior ``AI_PROVIDER`` "
            "value — it always auto-detects from the catalog vendor. The "
            "'skip switching when currently public' branch was removed; this "
            "test exercises behavior that no longer exists and should be "
            "rewritten against the new auto-detect contract if we want to "
            "pin it."
        )
    )
    async def test_no_provider_switch_for_public(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
    ) -> None:
        """Should not update provider when current is 'public' (obsolete)."""


@pytest.mark.asyncio
class TestGetModelInfo:
    """Tests for get_model_info() async function."""

    async def test_model_exists(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
        sample_prices: list[LLMPrice],
        sample_modalities: list[LLMModality],
    ) -> None:
        """Should return full details when model exists."""
        with patch(
            "app.services.ai.domains.llm.llm_service.get_async_session",
            mock_async_session,
        ):
            details = await get_model_info("gpt-4o")

        assert details is not None
        assert details.model_id == "gpt-4o"
        assert details.title == "GPT-4o"
        assert details.vendor == "openai"
        assert details.context_window == 128000
        assert details.streamable is True
        assert details.enabled is True
        assert details.input_price == 5.0
        assert details.output_price == 15.0
        # Modalities may be formatted as enum repr or value
        assert any("text" in m.lower() for m in details.modalities)
        assert any("image" in m.lower() for m in details.modalities)

    async def test_model_not_found(
        self,
        mock_async_session,
    ) -> None:
        """Should return None when model not in catalog."""
        with patch(
            "app.services.ai.domains.llm.llm_service.get_async_session",
            mock_async_session,
        ):
            details = await get_model_info("nonexistent-model")

        assert details is None

    async def test_model_without_pricing(
        self,
        mock_async_session,
        sample_models: list[LargeLanguageModel],
    ) -> None:
        """Should handle models without pricing data."""
        with patch(
            "app.services.ai.domains.llm.llm_service.get_async_session",
            mock_async_session,
        ):
            # gpt-3.5-turbo has no price in sample_prices
            details = await get_model_info("gpt-3.5-turbo")

        assert details is not None
        assert details.input_price is None
        assert details.output_price is None
