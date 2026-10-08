"""
Pydantic models for load test data structures.

Provides type safety and validation for load test configurations,
results, and analysis data.
"""

from typing import Any

from app.components.worker.constants import LoadTestTypes
from app.core.config import get_load_test_queue
from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


class LoadTestConfiguration(BaseModel):
    """Load test configuration with validation and defaults."""

    num_tasks: int = Field(default=100, ge=1, description="Number of tasks to spawn")
    task_type: LoadTestTypes = Field(
        default=LoadTestTypes.CPU_INTENSIVE, description="Type of load test to run"
    )
    batch_size: int = Field(default=10, ge=1, le=100, description="Tasks per batch")
    delay_ms: int = Field(
        default=0, ge=0, le=5000, description="Delay between batches (ms)"
    )
    target_queue: str | None = Field(
        default=None, description="Target queue for testing"
    )

    @field_validator("target_queue")
    @classmethod
    def set_default_queue(cls, v: str | None) -> str:
        """Set default queue if not specified."""
        return v if v is not None else get_load_test_queue()

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Convert configuration to dictionary for task enqueueing."""
        data = super().model_dump(**kwargs)
        # Convert enum to string value for task enqueueing
        data["task_type"] = self.task_type.value
        return data


class LoadTestMetrics(BaseModel):
    """Metrics from load test execution."""

    tasks_sent: int = Field(..., ge=0, description="Total tasks enqueued")
    tasks_completed: int = Field(..., ge=0, description="Successfully completed tasks")
    tasks_failed: int = Field(0, ge=0, description="Failed tasks")
    total_duration_seconds: float = Field(..., ge=0, description="Total test duration")
    overall_throughput: float = Field(
        0, ge=0, description="Overall throughput (tasks/sec)"
    )
    failure_rate_percent: float = Field(
        0, ge=0, le=100, description="Failure rate percentage"
    )
    completion_percentage: float = Field(
        0, ge=0, le=100, description="Completion percentage"
    )
    average_throughput_per_second: float = Field(
        0, ge=0, description="Average throughput"
    )
    monitor_duration_seconds: float = Field(0, ge=0, description="Monitoring duration")

    @field_validator("tasks_completed")
    @classmethod
    def completed_not_exceed_sent(cls, v: int, info: ValidationInfo) -> int:
        """Ensure completed tasks don't exceed sent tasks."""
        if info.data and "tasks_sent" in info.data and v > info.data["tasks_sent"]:
            raise ValueError(
                f"Completed tasks ({v}) cannot exceed sent tasks "
                f"({info.data['tasks_sent']})"
            )
        return v

    @field_validator("tasks_failed")
    @classmethod
    def failed_not_exceed_sent(cls, v: int, info: ValidationInfo) -> int:
        """Ensure failed tasks don't exceed sent tasks."""
        if info.data and "tasks_sent" in info.data and v > info.data["tasks_sent"]:
            raise ValueError(
                f"Failed tasks ({v}) cannot exceed sent tasks "
                f"({info.data['tasks_sent']})"
            )
        return v

    @field_validator("failure_rate_percent")
    @classmethod
    def validate_failure_rate_consistency(cls, v: float, info: ValidationInfo) -> float:
        """Ensure failure rate percentage matches task counts."""
        if info.data and "tasks_sent" in info.data and "tasks_failed" in info.data:
            tasks_sent = info.data["tasks_sent"]
            tasks_failed = info.data["tasks_failed"]
            if tasks_sent > 0:
                calculated_rate = (tasks_failed / tasks_sent) * 100
                # Allow small floating point differences (within 0.1%)
                if abs(v - calculated_rate) > 0.1:
                    raise ValueError(
                        f"Failure rate {v}% doesn't match task counts "
                        f"({tasks_failed}/{tasks_sent} = {calculated_rate:.1f}%)"
                    )
        return v


class PerformanceAnalysis(BaseModel):
    """Performance analysis results."""

    throughput_rating: str = Field(
        ...,
        pattern=r"^(unknown|poor|fair|good|excellent)$",
        description="Throughput performance rating",
    )
    efficiency_rating: str = Field(
        ...,
        pattern=r"^(unknown|poor|fair|good|excellent)$",
        description="Task completion efficiency",
    )
    queue_pressure: str = Field(
        ...,
        pattern=r"^(unknown|low|medium|high)$",
        description="Queue saturation level",
    )


class ValidationStatus(BaseModel):
    """Test execution validation status."""

    test_type_verified: bool = Field(
        default=False, description="Test type executed correctly"
    )
    expected_metrics_present: bool = Field(
        default=False, description="Expected metrics are present"
    )
    performance_signature_match: str = Field(
        default="unknown",
        pattern=r"^(unknown|verified|partial|failed)$",
        description="Performance matches expected patterns",
    )
    issues: list[str] = Field(default_factory=list, description="Validation issues")


class TestTypeInfo(BaseModel):
    """Information about a specific test type."""

    name: str = Field(..., description="Human-readable test name")
    description: str = Field(..., description="Test description")
    expected_metrics: list[str] = Field(..., description="Expected result metrics")
    performance_signature: str = Field(..., description="Expected performance pattern")
    typical_duration_ms: str = Field(..., description="Typical execution time")
    concurrency_impact: str = Field(..., description="Concurrency characteristics")
    validation_keys: list[str] = Field(..., description="Keys for result validation")


class LoadTestAnalysis(BaseModel):
    """Complete load test analysis."""

    test_type_info: TestTypeInfo = Field(..., description="Test type information")
    performance_analysis: PerformanceAnalysis = Field(
        ..., description="Performance analysis"
    )
    validation_status: ValidationStatus = Field(..., description="Validation results")
    recommendations: list[str] = Field(..., description="Improvement recommendations")


class LoadTestResult(BaseModel):
    """Complete load test result with analysis."""

    task: str = Field(default="worker_load_test", description="Task name")
    status: str = Field(
        ...,
        pattern=r"^(completed|failed|timed_out)$",
        description="Test execution status",
    )
    test_id: str = Field(..., description="Unique test identifier")
    configuration: LoadTestConfiguration = Field(..., description="Test configuration")
    metrics: LoadTestMetrics = Field(..., description="Execution metrics")
    start_time: str | None = Field(None, description="Test start time")
    end_time: str | None = Field(None, description="Test end time")
    task_ids: list[str] = Field(default_factory=list, description="Individual task IDs")
    error: str | None = Field(None, description="Error message if failed")
    analysis: LoadTestAnalysis | None = Field(None, description="Performance analysis")

    @model_validator(mode="after")
    def validate_status_consistency(self) -> "LoadTestResult":
        """Validate status consistency with error field."""
        if self.status == "failed" and not self.error:
            raise ValueError("Failed status requires error message")
        return self


class OrchestratorRawResult(BaseModel):
    """A run's tally (``runs.tally``), turned into a ``LoadTestResult``."""

    test_id: str = Field(..., description="Test identifier")
    task_type: str = Field(..., description="Task type executed")
    tasks_sent: int = Field(..., description="Tasks enqueued")
    tasks_completed: int = Field(0, description="Successfully completed")
    tasks_failed: int = Field(0, description="Failed tasks")
    total_duration_seconds: float = Field(0, description="Start to last finish")
    overall_throughput_per_second: float = Field(0, description="Completed per second")
    failure_rate_percent: float = Field(0, description="Failure rate")
    completion_percentage: float = Field(0, description="Completion rate")
    batch_size: int = Field(1, description="Batch size used")
    delay_ms: int = Field(0, description="Delay between batches")
    target_queue: str = Field(..., description="Target queue")
    start_time: str | None = Field(None, description="Start time")
    end_time: str | None = Field(None, description="End time")
    error: str | None = Field(None, description="Why sending stopped, if it did")

    def to_load_test_result(self) -> LoadTestResult:
        """Transform to standard LoadTestResult format."""
        return LoadTestResult(
            status="failed" if self.error else "completed",
            test_id=self.test_id,
            configuration=LoadTestConfiguration(
                task_type=LoadTestTypes(self.task_type),
                num_tasks=max(self.tasks_sent, 1),
                batch_size=self.batch_size,
                delay_ms=self.delay_ms,
                target_queue=self.target_queue,
            ),
            metrics=LoadTestMetrics(
                tasks_sent=self.tasks_sent,
                tasks_completed=self.tasks_completed,
                tasks_failed=self.tasks_failed,
                total_duration_seconds=self.total_duration_seconds,
                overall_throughput=self.overall_throughput_per_second,
                failure_rate_percent=self.failure_rate_percent,
                completion_percentage=self.completion_percentage,
            ),
            start_time=self.start_time,
            end_time=self.end_time,
            error=self.error,
        )
