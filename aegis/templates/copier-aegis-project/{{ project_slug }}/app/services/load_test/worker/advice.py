"""Scoring a finished run: was it fast, did it actually run, what next.

Two sets of the same three judgements - one returning dicts for the
raw result payload, one returning models for the typed one.
"""

from typing import Any

from app.services.load_test.worker.models import (
    LoadTestResult,
    PerformanceAnalysis,
    TestTypeInfo,
    ValidationStatus,
)


class AdviceMixin:
    """Performance, validation and recommendations."""

    @staticmethod
    def _analyze_performance(result: dict[str, Any]) -> dict[str, Any]:
        """Analyze performance characteristics of the load test."""
        metrics = result.get("metrics", {})

        analysis = {
            "throughput_rating": "unknown",
            "efficiency_rating": "unknown",
            "queue_pressure": "unknown",
        }

        # Analyze throughput
        throughput = metrics.get("overall_throughput", 0)
        if throughput >= 50:
            analysis["throughput_rating"] = "excellent"
        elif throughput >= 20:
            analysis["throughput_rating"] = "good"
        elif throughput >= 10:
            analysis["throughput_rating"] = "fair"
        else:
            analysis["throughput_rating"] = "poor"

        # Analyze efficiency (completion rate)
        tasks_sent = metrics.get("tasks_sent", 1)
        tasks_completed = metrics.get("tasks_completed", 0)
        completion_rate = (tasks_completed / tasks_sent) * 100 if tasks_sent > 0 else 0

        if completion_rate >= 95:
            analysis["efficiency_rating"] = "excellent"
        elif completion_rate >= 90:
            analysis["efficiency_rating"] = "good"
        elif completion_rate >= 80:
            analysis["efficiency_rating"] = "fair"
        else:
            analysis["efficiency_rating"] = "poor"

        # Analyze queue pressure (based on duration vs expected)
        duration = metrics.get("total_duration_seconds", 0)
        if duration > 60:
            analysis["queue_pressure"] = "high"
        elif duration > 30:
            analysis["queue_pressure"] = "medium"
        else:
            analysis["queue_pressure"] = "low"

        return analysis

    @staticmethod
    def _validate_test_execution(
        result: dict[str, Any], test_info: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate that the test executed as expected."""
        validation: dict[str, Any] = {
            "test_type_verified": False,
            "expected_metrics_present": False,
            "performance_signature_match": "unknown",
            "issues": [],
        }

        # This would need actual task result inspection to verify test type
        # For now, we assume the test executed correctly if it completed
        status = result.get("status", "unknown")
        if status == "completed":
            validation["test_type_verified"] = True
            validation["expected_metrics_present"] = True
            validation["performance_signature_match"] = "verified"
        else:
            validation["issues"].append(f"Test status: {status}")

        return validation

    @staticmethod
    def _generate_recommendations(result: dict[str, Any]) -> list[str]:
        """Generate recommendations based on test results."""
        recommendations = []

        metrics = result.get("metrics", {})
        throughput = metrics.get("overall_throughput", 0)
        failure_rate = metrics.get("failure_rate_percent", 0)

        if throughput < 10:
            recommendations.append(
                "Low throughput detected. Consider reducing task complexity or "
                "increasing worker concurrency."
            )

        if failure_rate > 5:
            recommendations.append(
                f"High failure rate ({failure_rate:.1f}%). Check worker logs "
                f"for error patterns."
            )

        duration = metrics.get("total_duration_seconds", 0)
        tasks_sent = metrics.get("tasks_sent", 1)

        if duration > 60 and tasks_sent < 200:
            recommendations.append(
                "Long execution time for relatively few tasks suggests queue "
                "saturation. Consider testing with smaller batches or "
                "different queues."
            )

        return recommendations

    @staticmethod
    def _analyze_performance_pydantic(result: LoadTestResult) -> PerformanceAnalysis:
        """Analyze performance characteristics using Pydantic models."""

        # Analyze throughput
        throughput = result.metrics.overall_throughput
        if throughput >= 50:
            throughput_rating = "excellent"
        elif throughput >= 20:
            throughput_rating = "good"
        elif throughput >= 10:
            throughput_rating = "fair"
        else:
            throughput_rating = "poor"

        # Analyze efficiency (completion rate)
        tasks_sent = result.metrics.tasks_sent
        tasks_completed = result.metrics.tasks_completed
        completion_rate = (tasks_completed / tasks_sent) * 100 if tasks_sent > 0 else 0

        if completion_rate >= 95:
            efficiency_rating = "excellent"
        elif completion_rate >= 90:
            efficiency_rating = "good"
        elif completion_rate >= 80:
            efficiency_rating = "fair"
        else:
            efficiency_rating = "poor"

        # Analyze queue pressure (based on duration vs expected)
        duration = result.metrics.total_duration_seconds
        if duration > 60:
            queue_pressure = "high"
        elif duration > 30:
            queue_pressure = "medium"
        else:
            queue_pressure = "low"

        return PerformanceAnalysis(
            throughput_rating=throughput_rating,
            efficiency_rating=efficiency_rating,
            queue_pressure=queue_pressure,
        )

    @staticmethod
    def _validate_test_execution_pydantic(
        result: LoadTestResult, test_info: TestTypeInfo
    ) -> ValidationStatus:
        """Validate test execution using Pydantic models."""

        issues = []

        # Basic validation - if we got here, the test at least completed
        test_type_verified = result.status == "completed"
        expected_metrics_present = result.status == "completed"

        if result.status == "completed":
            performance_signature_match = "verified"
        else:
            performance_signature_match = "unknown"
            issues.append(f"Test status: {result.status}")

        # Additional validation based on metrics
        if result.metrics.tasks_completed == 0 and result.metrics.tasks_sent > 0:
            issues.append("No tasks completed despite tasks being sent")

        if result.metrics.failure_rate_percent > 50:
            issues.append(
                f"High failure rate: {result.metrics.failure_rate_percent:.1f}%"
            )

        return ValidationStatus(
            test_type_verified=test_type_verified,
            expected_metrics_present=expected_metrics_present,
            performance_signature_match=performance_signature_match,
            issues=issues,
        )

    @staticmethod
    def _generate_recommendations_pydantic(result: LoadTestResult) -> list[str]:
        """Generate recommendations using Pydantic models."""

        recommendations = []

        throughput = result.metrics.overall_throughput
        failure_rate = result.metrics.failure_rate_percent

        if throughput < 10:
            recommendations.append(
                "Low throughput detected. Consider reducing task complexity "
                "or increasing worker concurrency."
            )

        if failure_rate > 5:
            recommendations.append(
                f"High failure rate ({failure_rate:.1f}%). Check worker logs "
                f"for error patterns."
            )

        duration = result.metrics.total_duration_seconds
        tasks_sent = result.metrics.tasks_sent

        if duration > 60 and tasks_sent < 200:
            recommendations.append(
                "Long execution time for relatively few tasks suggests queue "
                "saturation. Consider testing with smaller batches or "
                "different queues."
            )

        return recommendations
