"""Tests for the runtime active-model override.

The catalog UI and the ``llm use`` CLI both switch models by writing this
override, so it is the source of truth at runtime and ``.env`` is only the
bootstrap default. The override has to take effect without a restart, which
is what these tests pin.
"""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai import active_model
from app.services.ai.config import get_ai_config


class _Settings:
    """A stand-in for the settings singleton (only what config reads)."""

    def __init__(self) -> None:
        self.AI_ENABLED = True
        self.AI_PROVIDER = "public"
        self.AI_MODEL = "auto"
        self.AI_TEMPERATURE = 0.7
        self.AI_MAX_TOKENS = 1000


class TestOverrideStorage:
    @pytest.mark.asyncio
    async def test_absent_by_default(self, async_db_session: AsyncSession) -> None:
        assert await active_model.get_active_override(async_db_session) is None

    @pytest.mark.asyncio
    async def test_set_then_read_round_trips(
        self, async_db_session: AsyncSession
    ) -> None:
        await active_model.set_active_override(
            async_db_session, model_id="gpt-4.1", provider="openai"
        )
        await async_db_session.commit()

        stored = await active_model.get_active_override(async_db_session)
        assert stored is not None
        assert stored.model_id == "gpt-4.1"
        assert stored.provider == "openai"

    @pytest.mark.asyncio
    async def test_switching_replaces_rather_than_appends(
        self, async_db_session: AsyncSession
    ) -> None:
        """One active model at a time, however many times you switch."""
        for model_id, provider in (
            ("gpt-4.1", "openai"),
            ("claude-sonnet-4", "anthropic"),
            ("llama3.1", "ollama"),
        ):
            await active_model.set_active_override(
                async_db_session, model_id=model_id, provider=provider
            )
        await async_db_session.commit()

        rows = await active_model.list_overrides(async_db_session)
        assert len(rows) == 1
        assert rows[0].model_id == "llama3.1"
        assert rows[0].provider == "ollama"


class TestOwnerScoping:
    """The row carries a nullable owner from day one.

    NULL is the install-wide default and the only value a no-auth stack ever
    writes. Carrying the column now means per-user selection later is a
    resolution change rather than a migration on a shipped table - the same
    split the finance service uses, where the column always exists and only
    the FK to ``user`` is added when auth is present.
    """

    @pytest.mark.asyncio
    async def test_default_selection_has_no_owner(
        self, async_db_session: AsyncSession
    ) -> None:
        await active_model.set_active_override(
            async_db_session, model_id="gpt-4.1", provider="openai"
        )
        await async_db_session.commit()

        stored = await active_model.get_active_override(async_db_session)
        assert stored is not None
        assert stored.owner_user_id is None

    @pytest.mark.asyncio
    async def test_owners_do_not_clobber_each_other(
        self, async_db_session: AsyncSession
    ) -> None:
        await active_model.set_active_override(
            async_db_session, model_id="gpt-4.1", provider="openai"
        )
        await active_model.set_active_override(
            async_db_session,
            model_id="claude-sonnet-4",
            provider="anthropic",
            owner_user_id=7,
        )
        await async_db_session.commit()

        assert len(await active_model.list_overrides(async_db_session)) == 2
        default = await active_model.get_active_override(async_db_session)
        owned = await active_model.get_active_override(
            async_db_session, owner_user_id=7
        )
        assert default is not None and default.model_id == "gpt-4.1"
        assert owned is not None and owned.model_id == "claude-sonnet-4"

    @pytest.mark.asyncio
    async def test_switching_replaces_only_that_owners_row(
        self, async_db_session: AsyncSession
    ) -> None:
        for model_id in ("gpt-4.1", "gpt-4o"):
            await active_model.set_active_override(
                async_db_session,
                model_id=model_id,
                provider="openai",
                owner_user_id=7,
            )
        await async_db_session.commit()

        rows = await active_model.list_overrides(async_db_session)
        assert len(rows) == 1
        assert rows[0].model_id == "gpt-4o"

    @pytest.mark.asyncio
    async def test_an_owner_without_a_row_falls_back_to_the_default(
        self, async_db_session: AsyncSession
    ) -> None:
        """Resolution order: the user's row, then the install-wide one."""
        await active_model.set_active_override(
            async_db_session, model_id="gpt-4.1", provider="openai"
        )
        await async_db_session.commit()

        resolved = await active_model.resolve_override(
            async_db_session, owner_user_id=99
        )
        assert resolved is not None
        assert resolved.model_id == "gpt-4.1"
        assert resolved.owner_user_id is None


class TestSettingsApplication:
    def test_apply_mutates_the_live_settings(self) -> None:
        """The point of the override: no restart, no .env rewrite."""
        settings = _Settings()
        active_model.apply_to_settings(settings, model_id="gpt-4.1", provider="openai")
        assert settings.AI_MODEL == "gpt-4.1"
        assert settings.AI_PROVIDER == "openai"

    def test_apply_without_a_provider_leaves_it_alone(self) -> None:
        """An Ollama-only or catalog-less model must not blank the provider."""
        settings = _Settings()
        settings.AI_PROVIDER = "anthropic"
        active_model.apply_to_settings(settings, model_id="some-model", provider=None)
        assert settings.AI_MODEL == "some-model"
        assert settings.AI_PROVIDER == "anthropic"

    def test_applied_override_reaches_the_resolved_ai_config(self) -> None:
        """``get_ai_config`` stays sync; the override arrives through settings."""
        settings = _Settings()
        active_model.apply_to_settings(
            settings, model_id="claude-sonnet-4", provider="anthropic"
        )
        config = get_ai_config(settings)
        assert config.model == "claude-sonnet-4"
        assert config.provider.value == "anthropic"

    @pytest.mark.asyncio
    async def test_load_into_settings_applies_the_stored_override(
        self, async_db_session: AsyncSession
    ) -> None:
        """What the startup hook does, so a restart keeps the choice."""
        await active_model.set_active_override(
            async_db_session, model_id="gpt-4.1", provider="openai"
        )
        await async_db_session.commit()

        settings = _Settings()
        applied = await active_model.load_into_settings(async_db_session, settings)
        assert applied is True
        assert settings.AI_MODEL == "gpt-4.1"
        assert settings.AI_PROVIDER == "openai"

    @pytest.mark.asyncio
    async def test_load_into_settings_is_a_noop_without_an_override(
        self, async_db_session: AsyncSession
    ) -> None:
        settings = _Settings()
        applied = await active_model.load_into_settings(async_db_session, settings)
        assert applied is False
        assert settings.AI_MODEL == "auto"
        assert settings.AI_PROVIDER == "public"


class TestClearOverride:
    """Clearing hands control back to .env, live, without a restart.

    The inverse path has to exist: a stored row otherwise shadows every
    later .env edit, and "I rebuilt and it still shows the old model" is
    exactly the confusion that costs an hour.
    """

    def setup_method(self) -> None:
        # The .env capture is once-per-process; isolate it per test.
        active_model._env_defaults = None

    def teardown_method(self) -> None:
        active_model._env_defaults = None

    @pytest.mark.asyncio
    async def test_clear_deletes_the_row_and_restores_env_values(
        self, async_db_session: AsyncSession
    ) -> None:
        settings = _Settings()
        await active_model.set_active_override(
            async_db_session, model_id="qwen2.5-coder:32b", provider="ollama"
        )
        await async_db_session.commit()
        # Boot: the startup hook captures .env before applying the override.
        await active_model.load_into_settings(async_db_session, settings)
        assert settings.AI_MODEL == "qwen2.5-coder:32b"

        cleared = await active_model.clear_active_override(async_db_session, settings)
        await async_db_session.commit()

        assert cleared is True
        assert await active_model.get_active_override(async_db_session) is None
        assert settings.AI_MODEL == "auto"
        assert settings.AI_PROVIDER == "public"

    @pytest.mark.asyncio
    async def test_clear_without_a_row_is_a_quiet_noop(
        self, async_db_session: AsyncSession
    ) -> None:
        settings = _Settings()
        cleared = await active_model.clear_active_override(async_db_session, settings)
        assert cleared is False
        assert settings.AI_MODEL == "auto"
        assert settings.AI_PROVIDER == "public"

    @pytest.mark.asyncio
    async def test_env_capture_survives_repeated_switches(
        self, async_db_session: AsyncSession
    ) -> None:
        """However many models were tried, reset lands on the .env value."""
        settings = _Settings()
        for model_id in ("gpt-oss:20b", "qwen3:30b-a3b"):
            active_model.apply_to_settings(
                settings, model_id=model_id, provider="ollama"
            )
            await active_model.set_active_override(
                async_db_session, model_id=model_id, provider="ollama"
            )
        await async_db_session.commit()
        assert settings.AI_MODEL == "qwen3:30b-a3b"

        await active_model.clear_active_override(async_db_session, settings)
        await async_db_session.commit()

        assert settings.AI_MODEL == "auto"
        assert settings.AI_PROVIDER == "public"

    def test_env_default_model_reports_the_capture(self) -> None:
        settings = _Settings()
        assert active_model.env_default_model() is None
        active_model.apply_to_settings(settings, model_id="x", provider=None)
        assert active_model.env_default_model() == "auto"
