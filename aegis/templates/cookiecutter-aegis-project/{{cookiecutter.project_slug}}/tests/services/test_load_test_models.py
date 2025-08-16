"""
Unit tests for load test Pydantic models.

Tests validation, constraints, and data transformation for all load test models.
"""

import pytest
from pydantic import ValidationError

from app.services.load_test_models import (
    LoadTestConfiguration,
    LoadTestError,
    LoadTestMetrics,
    LoadTestResult,
    OrchestratorRawResult,
    PerformanceAnalysis,
    TestTypeInfo,
    ValidationStatus,
)


class TestLoadTestConfiguration:
    """Test LoadTestConfiguration model validation."""

    def test_valid_configuration(self):
        """Test creating valid configuration."""
        config = LoadTestConfiguration(
            task_type="cpu_intensive",
            num_tasks=100,
            batch_size=10,
            delay_ms=50,
            target_queue="load_test"
        )
        
        assert config.task_type == "cpu_intensive"
        assert config.num_tasks == 100
        assert config.batch_size == 10
        assert config.delay_ms == 50
        assert config.target_queue == "load_test"

    def test_num_tasks_validation(self):
        """Test num_tasks constraints."""
        # Valid range
        config = LoadTestConfiguration(
            task_type="cpu_intensive",
            num_tasks=50,
            batch_size=10,
            target_queue="load_test"
        )
        assert config.num_tasks == 50
        
        # Too low
        with pytest.raises(ValidationError, match="greater than or equal to 10"):
            LoadTestConfiguration(
                task_type="cpu_intensive",
                num_tasks=5,
                batch_size=10,
                target_queue="load_test"
            )
        
        # Too high
        with pytest.raises(ValidationError, match="less than or equal to 10000"):
            LoadTestConfiguration(
                task_type="cpu_intensive",
                num_tasks=20000,
                batch_size=10,
                target_queue="load_test"
            )

    def test_batch_size_validation(self):
        """Test batch_size constraints."""
        # Valid range
        config = LoadTestConfiguration(
            task_type="cpu_intensive",
            num_tasks=100,
            batch_size=25,
            target_queue="load_test"
        )
        assert config.batch_size == 25
        
        # Too low
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            LoadTestConfiguration(
                task_type="cpu_intensive",
                num_tasks=100,
                batch_size=0,
                target_queue="load_test"
            )
        
        # Too high
        with pytest.raises(ValidationError, match="less than or equal to 100"):
            LoadTestConfiguration(
                task_type="cpu_intensive",
                num_tasks=100,
                batch_size=150,
                target_queue="load_test"
            )

    def test_delay_ms_validation(self):
        """Test delay_ms constraints."""
        # Valid range
        config = LoadTestConfiguration(
            task_type="cpu_intensive",
            num_tasks=100,
            batch_size=10,
            delay_ms=1000,
            target_queue="load_test"
        )
        assert config.delay_ms == 1000
        
        # Too low (negative)
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            LoadTestConfiguration(
                task_type="cpu_intensive",
                num_tasks=100,
                batch_size=10,
                delay_ms=-100,
                target_queue="load_test"
            )
        
        # Too high
        with pytest.raises(ValidationError, match="less than or equal to 5000"):
            LoadTestConfiguration(
                task_type="cpu_intensive",
                num_tasks=100,
                batch_size=10,
                delay_ms=10000,
                target_queue="load_test"
            )


class TestLoadTestMetrics:
    """Test LoadTestMetrics model validation."""

    def test_valid_metrics(self):
        """Test creating valid metrics."""
        metrics = LoadTestMetrics(
            tasks_sent=100,
            tasks_completed=95,
            tasks_failed=5,
            total_duration_seconds=30.5,
            overall_throughput=3.1,
            failure_rate_percent=5.0
        )
        
        assert metrics.tasks_sent == 100
        assert metrics.tasks_completed == 95
        assert metrics.tasks_failed == 5
        assert metrics.total_duration_seconds == 30.5
        assert metrics.overall_throughput == 3.1
        assert metrics.failure_rate_percent == 5.0

    def test_completed_not_exceed_sent_validator(self):
        """Test that completed tasks cannot exceed sent tasks."""
        # Valid case
        metrics = LoadTestMetrics(
            tasks_sent=100,
            tasks_completed=90,
            total_duration_seconds=30.0
        )
        assert metrics.tasks_completed == 90
        
        # Invalid case - more completed than sent
        with pytest.raises(ValidationError, match="Completed tasks \\(150\\) cannot exceed sent tasks \\(100\\)"):
            LoadTestMetrics(
                tasks_sent=100,
                tasks_completed=150,
                total_duration_seconds=30.0
            )

    def test_failure_rate_consistency_validator(self):
        """Test that failure rate matches task counts."""
        # Valid case - 10 failed out of 100 = 10%
        metrics = LoadTestMetrics(
            tasks_sent=100,
            tasks_completed=90,
            tasks_failed=10,
            total_duration_seconds=30.0,
            failure_rate_percent=10.0
        )
        assert metrics.failure_rate_percent == 10.0
        
        # Invalid case - mismatch between counts and percentage
        with pytest.raises(ValidationError, match="Failure rate 50.0% doesn't match task counts"):
            LoadTestMetrics(
                tasks_sent=100,
                tasks_completed=90,
                tasks_failed=10,  # Should be 10%, not 50%
                total_duration_seconds=30.0,
                failure_rate_percent=50.0
            )

    def test_negative_values_rejected(self):
        """Test that negative values are rejected."""
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            LoadTestMetrics(
                tasks_sent=-10,
                tasks_completed=0,
                total_duration_seconds=30.0
            )
        
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            LoadTestMetrics(
                tasks_sent=100,
                tasks_completed=-5,
                total_duration_seconds=30.0
            )

    def test_percentage_bounds(self):
        """Test percentage fields are within valid ranges."""
        # Valid percentages
        metrics = LoadTestMetrics(
            tasks_sent=100,
            tasks_completed=100,
            total_duration_seconds=30.0,
            failure_rate_percent=0.0,
            completion_percentage=100.0
        )
        assert metrics.failure_rate_percent == 0.0
        assert metrics.completion_percentage == 100.0
        
        # Invalid percentage - over 100%
        with pytest.raises(ValidationError, match="less than or equal to 100"):
            LoadTestMetrics(
                tasks_sent=100,
                tasks_completed=100,
                total_duration_seconds=30.0,
                failure_rate_percent=150.0
            )


class TestPerformanceAnalysis:
    """Test PerformanceAnalysis model validation."""

    def test_valid_ratings(self):
        """Test valid rating values."""
        analysis = PerformanceAnalysis(
            throughput_rating="excellent",
            efficiency_rating="good",
            queue_pressure="low"
        )
        
        assert analysis.throughput_rating == "excellent"
        assert analysis.efficiency_rating == "good"
        assert analysis.queue_pressure == "low"

    def test_invalid_rating_values(self):
        """Test that invalid rating values are rejected."""
        with pytest.raises(ValidationError, match="String should match pattern"):
            PerformanceAnalysis(
                throughput_rating="amazing",  # Not in allowed values
                efficiency_rating="good",
                queue_pressure="low"
            )
        
        with pytest.raises(ValidationError, match="String should match pattern"):
            PerformanceAnalysis(
                throughput_rating="excellent",
                efficiency_rating="terrible",  # Not in allowed values
                queue_pressure="low"
            )

    def test_all_valid_rating_combinations(self):
        """Test all valid rating value combinations."""
        valid_ratings = ["unknown", "poor", "fair", "good", "excellent"]
        valid_pressures = ["unknown", "low", "medium", "high"]
        
        for throughput in valid_ratings:
            for efficiency in valid_ratings:
                for pressure in valid_pressures:
                    analysis = PerformanceAnalysis(
                        throughput_rating=throughput,
                        efficiency_rating=efficiency,
                        queue_pressure=pressure
                    )
                    assert analysis.throughput_rating == throughput
                    assert analysis.efficiency_rating == efficiency
                    assert analysis.queue_pressure == pressure


class TestValidationStatus:
    """Test ValidationStatus model validation."""

    def test_valid_status(self):
        """Test creating valid validation status."""
        status = ValidationStatus(
            test_type_verified=True,
            expected_metrics_present=True,
            performance_signature_match="verified",
            issues=["Some issue"]
        )
        
        assert status.test_type_verified is True
        assert status.expected_metrics_present is True
        assert status.performance_signature_match == "verified"
        assert status.issues == ["Some issue"]

    def test_default_values(self):
        """Test default values for optional fields."""
        status = ValidationStatus()
        
        assert status.test_type_verified is False
        assert status.expected_metrics_present is False
        assert status.performance_signature_match == "unknown"
        assert status.issues == []

    def test_invalid_signature_match_values(self):
        """Test that invalid signature match values are rejected."""
        with pytest.raises(ValidationError, match="String should match pattern"):
            ValidationStatus(
                performance_signature_match="definitely"  # Not in allowed values
            )


class TestLoadTestResult:
    """Test LoadTestResult model validation."""

    def test_valid_result(self):
        """Test creating valid load test result."""
        config = LoadTestConfiguration(
            task_type="cpu_intensive",
            num_tasks=100,
            batch_size=10,
            target_queue="load_test"
        )
        
        metrics = LoadTestMetrics(
            tasks_sent=100,
            tasks_completed=100,
            total_duration_seconds=30.0
        )
        
        result = LoadTestResult(
            status="completed",
            test_id="test-123",
            configuration=config,
            metrics=metrics
        )
        
        assert result.status == "completed"
        assert result.test_id == "test-123"
        assert result.task == "load_test_orchestrator"  # Default value
        assert result.configuration.task_type == "cpu_intensive"
        assert result.metrics.tasks_sent == 100

    def test_invalid_status_values(self):
        """Test that invalid status values are rejected."""
        config = LoadTestConfiguration(
            task_type="cpu_intensive",
            num_tasks=100,
            batch_size=10,
            target_queue="load_test"
        )
        
        metrics = LoadTestMetrics(
            tasks_sent=100,
            tasks_completed=100,
            total_duration_seconds=30.0
        )
        
        with pytest.raises(ValidationError, match="String should match pattern"):
            LoadTestResult(
                status="running",  # Not in allowed values
                test_id="test-123",
                configuration=config,
                metrics=metrics
            )

    def test_status_consistency_validator(self):
        """Test status consistency validation."""
        config = LoadTestConfiguration(
            task_type="cpu_intensive",
            num_tasks=100,
            batch_size=10,
            target_queue="load_test"
        )
        
        # Failed status without error should be rejected
        metrics = LoadTestMetrics(
            tasks_sent=100,
            tasks_completed=0,
            total_duration_seconds=30.0
        )
        
        with pytest.raises(ValidationError, match="Failed status requires error message"):
            LoadTestResult(
                status="failed",
                test_id="test-123",
                configuration=config,
                metrics=metrics
                # Missing error field
            )


class TestOrchestratorRawResult:
    """Test OrchestratorRawResult model and transformation."""

    def test_valid_raw_result(self):
        """Test creating valid orchestrator raw result."""
        raw_result = OrchestratorRawResult(
            test_id="test-123",
            task_type="cpu_intensive",
            tasks_sent=100,
            tasks_completed=95,
            tasks_failed=5,
            total_duration_seconds=30.5,
            overall_throughput_per_second=3.1,
            failure_rate_percent=5.0,
            completion_percentage=95.0,
            average_throughput_per_second=3.1,
            monitor_duration_seconds=30.0,
            batch_size=10,
            target_queue="load_test"
        )
        
        assert raw_result.test_id == "test-123"
        assert raw_result.task_type == "cpu_intensive"
        assert raw_result.tasks_sent == 100
        assert raw_result.tasks_completed == 95

    def test_to_load_test_result_transformation(self):
        """Test transformation from raw result to LoadTestResult."""
        raw_result = OrchestratorRawResult(
            test_id="test-123",
            task_type="io_simulation",
            tasks_sent=50,
            tasks_completed=48,
            tasks_failed=2,
            total_duration_seconds=15.5,
            overall_throughput_per_second=3.1,
            failure_rate_percent=4.0,
            completion_percentage=96.0,
            average_throughput_per_second=3.1,
            monitor_duration_seconds=15.0,
            batch_size=5,
            target_queue="load_test",
            start_time="2023-01-01T10:00:00",
            end_time="2023-01-01T10:00:15",
            task_ids=["task1", "task2", "task3"]
        )
        
        result = raw_result.to_load_test_result()
        
        # Check main fields
        assert result.status == "completed"
        assert result.test_id == "test-123"
        assert result.task == "load_test_orchestrator"
        
        # Check configuration transformation
        assert result.configuration.task_type == "io_simulation"
        assert result.configuration.num_tasks == 50
        assert result.configuration.batch_size == 5
        assert result.configuration.target_queue == "load_test"
        
        # Check metrics transformation
        assert result.metrics.tasks_sent == 50
        assert result.metrics.tasks_completed == 48
        assert result.metrics.tasks_failed == 2
        assert result.metrics.total_duration_seconds == 15.5
        assert result.metrics.overall_throughput == 3.1
        assert result.metrics.failure_rate_percent == 4.0
        
        # Check optional fields
        assert result.start_time == "2023-01-01T10:00:00"
        assert result.end_time == "2023-01-01T10:00:15"
        assert result.task_ids == ["task1", "task2", "task3"]

    def test_transformation_with_minimal_data(self):
        """Test transformation with only required fields."""
        raw_result = OrchestratorRawResult(
            test_id="minimal-test",
            task_type="memory_operations",
            tasks_sent=10,
            tasks_completed=10,
            total_duration_seconds=5.0,
            batch_size=10,
            target_queue="system"
        )
        
        result = raw_result.to_load_test_result()
        
        assert result.test_id == "minimal-test"
        assert result.configuration.task_type == "memory_operations"
        assert result.metrics.tasks_sent == 10
        assert result.metrics.tasks_completed == 10
        assert result.metrics.tasks_failed == 0  # Default value
        assert result.start_time is None
        assert result.end_time is None
        assert result.task_ids == []


class TestLoadTestError:
    """Test LoadTestError model validation."""

    def test_valid_error(self):
        """Test creating valid load test error."""
        error = LoadTestError(
            status="failed",
            test_id="error-test-123",
            error="Task execution timeout",
            partial_info="Some tasks may have completed",
            tasks_sent=100
        )
        
        assert error.task == "load_test_orchestrator"  # Default
        assert error.status == "failed"
        assert error.test_id == "error-test-123"
        assert error.error == "Task execution timeout"
        assert error.partial_info == "Some tasks may have completed"
        assert error.tasks_sent == 100

    def test_invalid_status_values(self):
        """Test that invalid status values are rejected."""
        with pytest.raises(ValidationError, match="String should match pattern"):
            LoadTestError(
                status="completed",  # Should only be failed or timed_out
                test_id="error-test-123",
                error="Some error"
            )

    def test_required_fields(self):
        """Test that required fields are validated."""
        # Missing test_id
        with pytest.raises(ValidationError, match="Field required"):
            LoadTestError(
                status="failed",
                error="Some error"
            )
        
        # Missing error
        with pytest.raises(ValidationError, match="Field required"):
            LoadTestError(
                status="timed_out",
                test_id="error-test-123"
            )


# Integration test for real-world data shapes
class TestRealWorldDataShapes:
    """Test models with real-world data patterns."""

    def test_typical_successful_load_test_flow(self):
        """Test the complete flow with typical successful data."""
        # Raw orchestrator result (what comes from Redis)
        raw_data = {
            "test_id": "6273dc3c0a87424e93318244e1baf73b",
            "task_type": "io_simulation",
            "tasks_sent": 10,
            "tasks_completed": 10,
            "tasks_failed": 0,
            "total_duration_seconds": 2.02,
            "overall_throughput_per_second": 4.96,
            "failure_rate_percent": 0.0,
            "completion_percentage": 100.0,
            "average_throughput_per_second": 4.98,
            "monitor_duration_seconds": 2.01,
            "batch_size": 10,
            "delay_ms": 0,
            "target_queue": "load_test",
            "start_time": "2025-08-16T16:07:46.080128",
            "end_time": "2025-08-16T16:07:48.097005",
            "task_ids": [
                "ba4c043531c645f8956616eb60df1cc4",
                "8669123b761c4284a0423ccaa362e0b8"
            ]
        }
        
        # Validate raw result
        orchestrator_result = OrchestratorRawResult(**raw_data)
        assert orchestrator_result.test_id == "6273dc3c0a87424e93318244e1baf73b"
        
        # Transform to standard result
        load_test_result = orchestrator_result.to_load_test_result()
        assert load_test_result.status == "completed"
        assert load_test_result.metrics.tasks_completed == 10
        assert load_test_result.metrics.failure_rate_percent == 0.0
        
        # This validates that our Pydantic models handle real Redis data correctly

    def test_partial_failure_scenario(self):
        """Test handling of partial failures."""
        raw_data = {
            "test_id": "partial-fail-test",
            "task_type": "cpu_intensive",
            "tasks_sent": 100,
            "tasks_completed": 85,
            "tasks_failed": 15,
            "total_duration_seconds": 45.0,
            "overall_throughput_per_second": 1.89,
            "failure_rate_percent": 15.0,
            "completion_percentage": 85.0,
            "average_throughput_per_second": 1.89,
            "monitor_duration_seconds": 45.0,
            "batch_size": 20,
            "delay_ms": 100,
            "target_queue": "system"
        }
        
        # Should validate successfully despite failures
        orchestrator_result = OrchestratorRawResult(**raw_data)
        load_test_result = orchestrator_result.to_load_test_result()
        
        assert load_test_result.metrics.tasks_completed == 85
        assert load_test_result.metrics.tasks_failed == 15
        assert load_test_result.metrics.failure_rate_percent == 15.0

    def test_edge_case_minimum_values(self):
        """Test edge cases with minimum allowed values."""
        raw_data = {
            "test_id": "minimal",
            "task_type": "cpu_intensive",
            "tasks_sent": 10,  # Minimum allowed
            "tasks_completed": 1,
            "tasks_failed": 9,
            "total_duration_seconds": 0.1,
            "overall_throughput_per_second": 10.0,
            "failure_rate_percent": 90.0,
            "completion_percentage": 10.0,
            "average_throughput_per_second": 10.0,
            "monitor_duration_seconds": 0.1,
            "batch_size": 1,  # Minimum allowed
            "delay_ms": 0,
            "target_queue": "load_test"
        }
        
        orchestrator_result = OrchestratorRawResult(**raw_data)
        load_test_result = orchestrator_result.to_load_test_result()
        
        assert load_test_result.configuration.num_tasks == 10
        assert load_test_result.configuration.batch_size == 1
        assert load_test_result.metrics.failure_rate_percent == 90.0