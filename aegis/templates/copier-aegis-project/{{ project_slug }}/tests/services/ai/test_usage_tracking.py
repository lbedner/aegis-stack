"""Tests for LLM usage tracking service functions."""

from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

from sqlmodel import Session, select

from app.services.ai.models.llm import (
    LargeLanguageModel,
    LLMOrg,
    LLMPrice,
    LLMUsage,
)
from app.services.ai.service import AIService


class TestExtractUsage:
    """Tests for the _extract_usage method."""

    def test_extract_usage_response(self, ai_service: AIService) -> None:
        """Test extracting usage from a PydanticAI-style response.

        LangChain ``response_metadata`` was the old shape but the service
        now only reads PydanticAI's ``result.usage`` attribute
        (``request_tokens`` / ``response_tokens``). The LangChain branch
        was removed when PydanticAI became the sole AI framework, so the
        test now exercises the supported shape only.
        """
        # ``_extract_usage`` requires ``result.usage`` to be non-callable
        # (PydanticAI exposes usage as a data object, not a method). A bare
        # ``MagicMock()`` is callable, so we use ``SimpleNamespace`` to get
        # a plain attribute bag.
        from types import SimpleNamespace

        mock_result = MagicMock()
        mock_result.usage = SimpleNamespace(request_tokens=100, response_tokens=50)

        usage = ai_service._extract_usage(mock_result)

        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 50

    def test_extract_usage_missing_metadata(self, ai_service: AIService) -> None:
        """Test extracting usage when metadata is missing."""
        mock_result = MagicMock()
        mock_result.usage = None
        mock_result.response_metadata = {}

        usage = ai_service._extract_usage(mock_result)

        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0

    def test_extract_usage_no_usage_attribute(self, ai_service: AIService) -> None:
        """Test extracting usage when result has no usage info."""
        mock_result = MagicMock(spec=[])  # Empty spec, no attributes

        usage = ai_service._extract_usage(mock_result)

        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0


class TestRecordUsage:
    """Tests for the _record_usage method."""

    @contextmanager
    def _mock_db_session(self, session: Session) -> Generator[None, None, None]:
        """Patch ``db_session`` with a context manager wrapping the test session.

        Callers use this as ``with self._mock_db_session(s):`` and don't bind
        the yielded value — the side effect is the ``patch`` context. ``None``
        is the honest yielded type; pinning to ``MagicMock`` was wrong (the
        inner ``mock_session_cm`` is a callable contextmanager, not a mock).
        """

        @contextmanager
        def mock_session_cm() -> Generator[Session, None, None]:
            yield session

        # ``db_session`` is used from the service module (the LangChain inline
        # path) and from the shared ``usage_recording`` module (the pydantic-ai
        # delegation target). Patch it wherever it lives; ``usage_recording`` is
        # absent in LangChain/memory builds, so tolerate its absence.
        targets = ["app.services.ai.service.usage.db_session"]
        try:
            import app.services.ai.usage_recording  # noqa: F401

            targets.append("app.services.ai.usage_recording.db_session")
        except ImportError:
            pass

        with ExitStack() as stack:
            for target in targets:
                stack.enter_context(patch(target, mock_session_cm))
            yield

    def test_record_usage_success(
        self,
        db_session: Session,
        sample_llm: LargeLanguageModel,
        sample_price: LLMPrice,
        mock_ai_settings: Any,
    ) -> None:
        """Test recording usage creates an LLMUsage record."""
        mock_ai_settings.AI_MODEL = "gpt-4o"
        service = AIService(mock_ai_settings)

        with self._mock_db_session(db_session):
            service._record_usage(
                action="chat",
                usage={"input_tokens": 100, "output_tokens": 50},
                user_id="user-123",
                success=True,
            )

        # Verify usage was recorded
        stmt = select(LLMUsage).where(LLMUsage.user_id == "user-123")
        usage_record = db_session.exec(stmt).first()

        assert usage_record is not None
        assert usage_record.action == "chat"
        assert usage_record.input_tokens == 100
        assert usage_record.output_tokens == 50
        assert usage_record.success is True
        assert usage_record.model_id == sample_llm.model_id

    def test_record_usage_calculates_cost_correctly(
        self,
        db_session: Session,
        sample_llm: LargeLanguageModel,
        sample_price: LLMPrice,
        mock_ai_settings: Any,
    ) -> None:
        """Test that cost is calculated correctly from token usage and price."""
        mock_ai_settings.AI_MODEL = "gpt-4o"
        service = AIService(mock_ai_settings)

        # Price: input=$5/1M ($0.000005/token), output=$15/1M ($0.000015/token)
        # Usage: 1000 input tokens, 500 output tokens
        # Expected cost: (1000 * 0.000005) + (500 * 0.000015) = 0.005 + 0.0075 = 0.0125
        with self._mock_db_session(db_session):
            service._record_usage(
                action="chat",
                usage={"input_tokens": 1000, "output_tokens": 500},
                user_id="user-456",
            )

        stmt = select(LLMUsage).where(LLMUsage.user_id == "user-456")
        usage_record = db_session.exec(stmt).first()

        assert usage_record is not None
        assert abs(usage_record.total_cost - 0.0125) < 0.0001

    def test_record_usage_missing_llm_logs_warning(
        self,
        db_session: Session,
        mock_ai_settings: Any,
    ) -> None:
        """Missing LLM logs a warning but still records the usage row.

        Earlier behaviour dropped the row entirely when the LLM catalog
        didn't know the model. Current behaviour records it with zero
        cost so token totals don't silently vanish when a newly-enabled
        model hasn't been catalogued yet.
        """
        mock_ai_settings.AI_MODEL = "nonexistent-model"
        service = AIService(mock_ai_settings)

        with self._mock_db_session(db_session):
            # Should not raise, just log warning
            service._record_usage(
                action="chat",
                usage={"input_tokens": 100, "output_tokens": 50},
                user_id="user-789",
            )

        stmt = select(LLMUsage).where(LLMUsage.user_id == "user-789")
        usage_record = db_session.exec(stmt).first()
        assert usage_record is not None
        assert usage_record.model_id == "nonexistent-model"
        assert usage_record.total_cost == 0.0

    def test_record_usage_missing_price_zero_cost(
        self,
        db_session: Session,
        sample_llm: LargeLanguageModel,
        mock_ai_settings: Any,
    ) -> None:
        """Test that missing price results in zero cost."""
        # Note: sample_price fixture not used - no price in DB
        mock_ai_settings.AI_MODEL = "gpt-4o"
        service = AIService(mock_ai_settings)

        with self._mock_db_session(db_session):
            service._record_usage(
                action="chat",
                usage={"input_tokens": 100, "output_tokens": 50},
                user_id="user-noprice",
            )

        stmt = select(LLMUsage).where(LLMUsage.user_id == "user-noprice")
        usage_record = db_session.exec(stmt).first()

        assert usage_record is not None
        assert usage_record.total_cost == 0.0

    def test_record_usage_with_error(
        self,
        db_session: Session,
        sample_llm: LargeLanguageModel,
        sample_price: LLMPrice,
        mock_ai_settings: Any,
    ) -> None:
        """Test recording a failed request with error message."""
        mock_ai_settings.AI_MODEL = "gpt-4o"
        service = AIService(mock_ai_settings)

        with self._mock_db_session(db_session):
            service._record_usage(
                action="chat",
                usage={"input_tokens": 50, "output_tokens": 0},
                user_id="user-error",
                success=False,
                error_message="Rate limit exceeded",
            )

        stmt = select(LLMUsage).where(LLMUsage.user_id == "user-error")
        usage_record = db_session.exec(stmt).first()

        assert usage_record is not None
        assert usage_record.success is False
        assert usage_record.error_message == "Rate limit exceeded"
        assert usage_record.output_tokens == 0

    def test_record_usage_strips_vendor_prefix(
        self,
        db_session: Session,
        sample_llm: LargeLanguageModel,
        sample_price: LLMPrice,
        mock_ai_settings: Any,
    ) -> None:
        """Test that vendor prefix is stripped from model name."""
        # Model name with vendor prefix: "openai/gpt-4o"
        mock_ai_settings.AI_MODEL = "openai/gpt-4o"
        service = AIService(mock_ai_settings)

        with self._mock_db_session(db_session):
            service._record_usage(
                action="chat",
                usage={"input_tokens": 100, "output_tokens": 50},
                user_id="user-prefix",
            )

        stmt = select(LLMUsage).where(LLMUsage.user_id == "user-prefix")
        usage_record = db_session.exec(stmt).first()

        # Should find the LLM by stripped model_id "gpt-4o"
        assert usage_record is not None
        assert usage_record.model_id == sample_llm.model_id

    def test_record_usage_database_error_doesnt_fail(
        self,
        mock_ai_settings: Any,
    ) -> None:
        """Test that database errors don't crash the request."""
        mock_ai_settings.AI_MODEL = "gpt-4o"
        service = AIService(mock_ai_settings)

        # Mock db_session to raise on context manager entry
        failing_session = MagicMock()
        failing_session.return_value.__enter__.side_effect = Exception(
            "Database connection failed"
        )

        # Patch wherever the record path opens a session (service inline for
        # LangChain, the shared module for the pydantic-ai delegation).
        targets = ["app.services.ai.service.usage.db_session"]
        try:
            import app.services.ai.usage_recording  # noqa: F401

            targets.append("app.services.ai.usage_recording.db_session")
        except ImportError:
            pass

        with ExitStack() as stack:
            for target in targets:
                stack.enter_context(patch(target, failing_session))
            # Should not raise, just log error
            service._record_usage(
                action="chat",
                usage={"input_tokens": 100, "output_tokens": 50},
                user_id="user-fail",
            )

        # Test passes if no exception was raised


class TestGetUsageStats:
    """Tests for get_usage_stats aggregation method."""

    @contextmanager
    def _mock_db_session(self, session: Session) -> Generator[None, None, None]:
        """Patch ``db_session`` with a context manager wrapping the test session.

        Callers use this as ``with self._mock_db_session(s):`` and don't bind
        the yielded value — the side effect is the ``patch`` context. ``None``
        is the honest yielded type; pinning to ``MagicMock`` was wrong (the
        inner ``mock_session_cm`` is a callable contextmanager, not a mock).
        """

        @contextmanager
        def mock_session_cm() -> Generator[Session, None, None]:
            yield session

        with patch("app.services.ai.service.usage.db_session", mock_session_cm):
            yield

    def test_get_usage_stats_empty_database(
        self,
        db_session: Session,
        sample_llm: LargeLanguageModel,
        mock_ai_settings: Any,
    ) -> None:
        """Test stats return zeros when no usage records exist."""
        service = AIService(mock_ai_settings)
        with self._mock_db_session(db_session):
            stats = service.get_usage_stats()

        assert stats["total_tokens"] == 0
        assert stats["total_requests"] == 0
        assert stats["total_cost"] == 0.0
        assert stats["success_rate"] == 100.0
        assert stats["models"] == []
        assert stats["recent_activity"] == []

    def test_get_usage_stats_with_data(
        self,
        db_session: Session,
        sample_llm: LargeLanguageModel,
        mock_ai_settings: Any,
    ) -> None:
        """Test stats aggregation with usage records."""
        usage1 = LLMUsage(
            model_id=sample_llm.model_id,
            user_id="user-1",
            input_tokens=100,
            output_tokens=50,
            total_cost=0.001,
            success=True,
            action="chat",
        )
        usage2 = LLMUsage(
            model_id=sample_llm.model_id,
            user_id="user-1",
            input_tokens=200,
            output_tokens=100,
            total_cost=0.002,
            success=True,
            action="chat",
        )
        db_session.add(usage1)
        db_session.add(usage2)
        db_session.commit()

        service = AIService(mock_ai_settings)
        with self._mock_db_session(db_session):
            stats = service.get_usage_stats()

        assert stats["total_tokens"] == 450  # 100+50+200+100
        assert stats["input_tokens"] == 300
        assert stats["output_tokens"] == 150
        assert stats["total_requests"] == 2
        assert abs(stats["total_cost"] - 0.003) < 0.0001
        assert stats["success_rate"] == 100.0

    def test_get_usage_stats_model_breakdown(
        self,
        db_session: Session,
        sample_llm: LargeLanguageModel,
        sample_vendor: LLMOrg,
        mock_ai_settings: Any,
    ) -> None:
        """Test model breakdown aggregation."""
        usage = LLMUsage(
            model_id=sample_llm.model_id,
            user_id="user-1",
            input_tokens=100,
            output_tokens=50,
            total_cost=0.001,
            success=True,
            action="chat",
        )
        db_session.add(usage)
        db_session.commit()

        service = AIService(mock_ai_settings)
        with self._mock_db_session(db_session):
            stats = service.get_usage_stats()

        assert len(stats["models"]) == 1
        model_stats = stats["models"][0]
        assert model_stats["model_id"] == "gpt-4o"
        assert model_stats["vendor"] == "openai"
        assert model_stats["requests"] == 1
        assert model_stats["percentage"] == 100.0

    def test_get_usage_stats_recent_activity(
        self,
        db_session: Session,
        sample_llm: LargeLanguageModel,
        mock_ai_settings: Any,
    ) -> None:
        """Test recent activity returns correct entries."""
        usage = LLMUsage(
            model_id=sample_llm.model_id,
            user_id="user-1",
            input_tokens=100,
            output_tokens=50,
            total_cost=0.001,
            success=True,
            action="chat",
        )
        db_session.add(usage)
        db_session.commit()

        service = AIService(mock_ai_settings)
        with self._mock_db_session(db_session):
            stats = service.get_usage_stats(recent_limit=5)

        assert len(stats["recent_activity"]) == 1
        activity = stats["recent_activity"][0]
        # Recent activity reports the raw ``model_id`` (the stable
        # catalog key), not the display title. When the FK was dropped
        # and usage decoupled from the catalog, the join that pulled
        # display names went with it — orphan usage rows can outlive
        # their catalog entry, so the usable stable value is ``model_id``.
        assert activity["model"] == sample_llm.model_id
        # ``tokens`` was split into ``input_tokens`` + ``output_tokens``
        # so the UI can render prompt vs completion spend separately.
        assert activity["input_tokens"] == 100
        assert activity["output_tokens"] == 50
        assert activity["success"] is True
        assert activity["action"] == "chat"

    def test_get_usage_stats_user_filter(
        self,
        db_session: Session,
        sample_llm: LargeLanguageModel,
        mock_ai_settings: Any,
    ) -> None:
        """Test filtering by user_id."""
        usage1 = LLMUsage(
            model_id=sample_llm.model_id,
            user_id="user-1",
            input_tokens=100,
            output_tokens=50,
            total_cost=0.001,
            success=True,
            action="chat",
        )
        usage2 = LLMUsage(
            model_id=sample_llm.model_id,
            user_id="user-2",
            input_tokens=200,
            output_tokens=100,
            total_cost=0.002,
            success=True,
            action="chat",
        )
        db_session.add(usage1)
        db_session.add(usage2)
        db_session.commit()

        service = AIService(mock_ai_settings)
        with self._mock_db_session(db_session):
            stats = service.get_usage_stats(user_id="user-1")

        assert stats["total_requests"] == 1
        assert stats["total_tokens"] == 150

    def test_get_usage_stats_success_rate(
        self,
        db_session: Session,
        sample_llm: LargeLanguageModel,
        mock_ai_settings: Any,
    ) -> None:
        """Test success rate calculation with failures."""
        usage1 = LLMUsage(
            model_id=sample_llm.model_id,
            user_id="user-1",
            input_tokens=100,
            output_tokens=50,
            total_cost=0.001,
            success=True,
            action="chat",
        )
        usage2 = LLMUsage(
            model_id=sample_llm.model_id,
            user_id="user-1",
            input_tokens=100,
            output_tokens=0,
            total_cost=0.0,
            success=False,
            action="chat",
            error_message="Provider error",
        )
        db_session.add(usage1)
        db_session.add(usage2)
        db_session.commit()

        service = AIService(mock_ai_settings)
        with self._mock_db_session(db_session):
            stats = service.get_usage_stats()

        assert stats["total_requests"] == 2
        assert stats["success_rate"] == 50.0
