"""
Usage context models for AI self-awareness.

This module provides data structures for managing AI usage statistics
injection into chat conversations, giving Illiana awareness of her own
activity patterns, costs, and performance.
"""

from pydantic import BaseModel, Field


class UsageContext(BaseModel):
    """
    Context from AI usage statistics for injection into prompts.

    Gives the AI self-awareness about her own usage patterns,
    token consumption, costs, and success rates.
    """

    total_tokens: int = Field(default=0, description="Total tokens used")
    total_requests: int = Field(default=0, description="Total requests handled")
    total_cost: float = Field(default=0.0, description="Total cost in USD")
    success_rate: float = Field(default=100.0, description="Success rate percentage")
    top_model: str | None = Field(default=None, description="Most used model name")
    top_model_percentage: float = Field(
        default=0.0, description="Percentage of requests using top model"
    )
    recent_requests: int = Field(
        default=0, description="Number of recent requests returned"
    )

    def format_for_prompt(self, compact: bool = False) -> str:
        """
        Format usage data for injection into system prompt.

        Args:
            compact: Whether to use ultra-compact format for smaller models (Ollama)

        Returns:
            Formatted string for prompt injection
        """
        if self.total_requests == 0:
            return "Usage: No requests recorded yet"

        # Ultra-compact mode for Ollama and smaller models
        if compact:
            return (
                f"Usage: {self.total_requests} requests, "
                f"{self.total_tokens:,} tokens, ${self.total_cost:.2f}"
            )

        lines = [
            f"Usage: {self.total_requests:,} requests | "
            f"{self.total_tokens:,} tokens | ${self.total_cost:.2f} total cost",
            f"Success Rate: {self.success_rate:.1f}%",
        ]

        if self.top_model:
            lines.append(
                f"Top Model: {self.top_model} "
                f"({self.top_model_percentage:.0f}% of requests)"
            )

        lines.append(
            "  Report these stats when asked about your usage, activity, or costs."
        )

        return "\n".join(lines)

    def to_metadata(self) -> dict[str, float | int | str | None]:
        """
        Convert usage context to metadata format for storage.

        Returns:
            Summary metadata dictionary
        """
        return {
            "total_tokens": self.total_tokens,
            "total_requests": self.total_requests,
            "total_cost": self.total_cost,
            "success_rate": self.success_rate,
            "top_model": self.top_model,
        }


__all__ = ["UsageContext"]
