"""Tests for AI service API endpoints."""

from typing import Any
from unittest.mock import patch

import pytest
from app.integrations.main import create_integrated_app
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    app = create_integrated_app()
    return TestClient(app)


@pytest.fixture
def mock_usage_stats() -> dict[str, Any]:
    """Sample usage stats response."""
    return {
        "total_tokens": 1500,
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_cost": 0.015,
        "total_requests": 10,
        "success_rate": 95.0,
        "models": [
            {
                "model_id": "gpt-4o",
                "model_title": "GPT-4o",
                "vendor": "openai",
                "vendor_color": "#10A37F",
                "requests": 10,
                "tokens": 1500,
                "cost": 0.015,
                "percentage": 100.0,
            }
        ],
        "recent_activity": [
            {
                "timestamp": "2024-01-01T12:00:00",
                "model": "GPT-4o",
                # Response schema split ``tokens`` into ``input_tokens`` +
                # ``output_tokens`` so the UI can colorize prompt vs
                # completion spend separately.
                "input_tokens": 100,
                "output_tokens": 50,
                "cost": 0.0015,
                "success": True,
                "action": "chat",
            }
        ],
    }


class TestUsageStatsEndpoint:
    """Tests for /api/v1/ai/usage/stats endpoint."""

    def test_get_usage_stats_success(
        self, client: TestClient, mock_usage_stats: dict[str, Any]
    ) -> None:
        """Test successful usage stats retrieval."""
        with patch(
            "app.components.backend.api.ai.router.ai_service.get_usage_stats",
            return_value=mock_usage_stats,
        ):
            response = client.get("/api/v1/ai/usage/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total_tokens"] == 1500
        assert data["total_requests"] == 10
        assert len(data["models"]) == 1
        assert len(data["recent_activity"]) == 1

    def test_get_usage_stats_with_filters(
        self, client: TestClient, mock_usage_stats: dict[str, Any]
    ) -> None:
        """Test usage stats with query parameters."""
        with patch(
            "app.components.backend.api.ai.router.ai_service.get_usage_stats",
            return_value=mock_usage_stats,
        ) as mock_get:
            response = client.get(
                "/api/v1/ai/usage/stats",
                params={
                    "user_id": "test-user",
                    "recent_limit": 5,
                },
            )

        assert response.status_code == 200
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["user_id"] == "test-user"
        assert call_kwargs["recent_limit"] == 5

    def test_get_usage_stats_error_handling(self, client: TestClient) -> None:
        """Test error handling when service fails."""
        with patch(
            "app.components.backend.api.ai.router.ai_service.get_usage_stats",
            side_effect=Exception("Database error"),
        ):
            response = client.get("/api/v1/ai/usage/stats")

        assert response.status_code == 500
        assert "Failed to get usage stats" in response.json()["detail"]

    def test_get_usage_stats_response_schema(
        self, client: TestClient, mock_usage_stats: dict[str, Any]
    ) -> None:
        """Test response matches Pydantic schema."""
        with patch(
            "app.components.backend.api.ai.router.ai_service.get_usage_stats",
            return_value=mock_usage_stats,
        ):
            response = client.get("/api/v1/ai/usage/stats")

        assert response.status_code == 200
        data = response.json()

        # Verify all required fields present
        required_fields = [
            "total_tokens",
            "input_tokens",
            "output_tokens",
            "total_cost",
            "total_requests",
            "success_rate",
            "models",
            "recent_activity",
        ]
        for field in required_fields:
            assert field in data

        # Verify model stats structure
        if data["models"]:
            model = data["models"][0]
            assert "model_id" in model
            assert "vendor" in model
            assert "percentage" in model

    def test_get_usage_stats_empty_response(self, client: TestClient) -> None:
        """Test handling of empty usage data."""
        empty_stats = {
            "total_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_cost": 0.0,
            "total_requests": 0,
            "success_rate": 100.0,
            "models": [],
            "recent_activity": [],
        }
        with patch(
            "app.components.backend.api.ai.router.ai_service.get_usage_stats",
            return_value=empty_stats,
        ):
            response = client.get("/api/v1/ai/usage/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total_tokens"] == 0
        assert data["models"] == []
        assert data["recent_activity"] == []
