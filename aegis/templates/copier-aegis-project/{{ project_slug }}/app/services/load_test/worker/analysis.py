"""Reading a finished load test: what it was, and what it returned.

Identical for every worker backend, so the three backend services
inherit it rather than each carrying a copy. The transform takes
dramatiq's form, which falls back to the enqueue-phase duration and
throughput when the run reports none - the other backends never send
those keys, so the fallback costs them nothing.
"""

from typing import Any

from pydantic import ValidationError

from app.components.worker.constants import LoadTestTypes
from app.core.log import logger
from app.services.load_test.worker.advice import AdviceMixin
from app.services.load_test.worker.models import (
    LoadTestConfiguration,
    LoadTestMetrics,
    LoadTestResult,
    TestTypeInfo,
)


class AnalysisMixin(AdviceMixin):
    """The backend-independent half of ``LoadTestService``."""

    @staticmethod
    def get_test_type_info(test_type: LoadTestTypes | str) -> dict[str, Any]:
        """Get detailed information about a specific test type."""
        test_info = {
            LoadTestTypes.CPU_INTENSIVE: {
                "name": "CPU Intensive",
                "description": (
                    "Tests worker CPU processing with fibonacci calculations"
                ),
                "expected_metrics": [
                    "fibonacci_n",
                    "fibonacci_result",
                    "cpu_operations",
                ],
                "performance_signature": (
                    "CPU bound - should show computation time scaling with problem size"
                ),
                "typical_duration_ms": "1-10ms per task",
                "concurrency_impact": (
                    "Limited by CPU cores, benefits from parallel processing"
                ),
                "validation_keys": ["fibonacci_n", "fibonacci_result"],
            },
            LoadTestTypes.IO_SIMULATION: {
                "name": "I/O Simulation",
                "description": "Tests async I/O handling with simulated delays",
                "expected_metrics": [
                    "simulated_delay_ms",
                    "io_operations",
                    "async_operations",
                ],
                "performance_signature": (
                    "I/O bound - should show async concurrency benefits"
                ),
                "typical_duration_ms": ("5-30ms per task (includes simulated delays)"),
                "concurrency_impact": (
                    "Excellent with async - many tasks can run concurrently"
                ),
                "validation_keys": ["simulated_delay_ms", "io_operations"],
            },
            LoadTestTypes.MEMORY_OPERATIONS: {
                "name": "Memory Operations",
                "description": "Tests memory allocation and data structure operations",
                "expected_metrics": [
                    "allocation_size",
                    "list_sum",
                    "dict_keys",
                    "max_value",
                ],
                "performance_signature": (
                    "Memory bound - should show allocation/deallocation patterns"
                ),
                "typical_duration_ms": "1-5ms per task",
                "concurrency_impact": (
                    "Moderate - limited by memory bandwidth and GC pressure"
                ),
                "validation_keys": [
                    "allocation_size",
                    "list_sum",
                    "dict_keys",
                ],
            },
            LoadTestTypes.FAILURE_TESTING: {
                "name": "Failure Testing",
                "description": "Tests error handling with ~20% random failures",
                "expected_metrics": ["failure_rate", "error_types"],
                "performance_signature": (
                    "Mixed - tests resilience and error handling paths"
                ),
                "typical_duration_ms": "1-10ms per task (when successful)",
                "concurrency_impact": ("Tests worker recovery and error isolation"),
                "validation_keys": ["status"],
            },
        }
        return test_info.get(test_type, {})

    @staticmethod
    def _transform_orchestrator_result(
        orchestrator_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Transform orchestrator result to expected analysis format."""
        configuration = {
            "task_type": orchestrator_result.get("task_type", "unknown"),
            "num_tasks": orchestrator_result.get("tasks_sent", 0),
            "batch_size": orchestrator_result.get("batch_size", 0),
            "delay_ms": orchestrator_result.get("delay_ms", 0),
            "target_queue": orchestrator_result.get("target_queue", "unknown"),
        }

        # Use whichever duration/throughput is available (fire-and-forget vs monitored)
        duration = orchestrator_result.get(
            "total_duration_seconds"
        ) or orchestrator_result.get("enqueue_duration_seconds", 0)
        throughput = orchestrator_result.get(
            "overall_throughput_per_second"
        ) or orchestrator_result.get("enqueue_throughput_per_second", 0)

        metrics = {
            "tasks_sent": orchestrator_result.get("tasks_sent", 0),
            "tasks_completed": orchestrator_result.get("tasks_completed", 0),
            "tasks_failed": orchestrator_result.get("tasks_failed", 0),
            "total_duration_seconds": duration,
            "overall_throughput": throughput,
            "failure_rate_percent": orchestrator_result.get("failure_rate_percent", 0),
            "completion_percentage": orchestrator_result.get(
                "completion_percentage", 0
            ),
            "average_throughput_per_second": orchestrator_result.get(
                "average_throughput_per_second", 0
            ),
            "monitor_duration_seconds": orchestrator_result.get(
                "monitor_duration_seconds", 0
            ),
        }

        transformed = {
            "task": "load_test_orchestrator",
            "status": "completed",
            "test_id": orchestrator_result.get("test_id", "unknown"),
            "configuration": configuration,
            "metrics": metrics,
            "start_time": orchestrator_result.get("start_time"),
            "end_time": orchestrator_result.get("end_time"),
            "task_ids": orchestrator_result.get("task_ids", []),
        }

        return transformed

    @staticmethod
    def _analyze_load_test_result(
        result: LoadTestResult | dict[str, Any],
    ) -> LoadTestResult:
        """Add analysis and validation to load test results."""

        # Convert dict to model if needed
        if isinstance(result, dict):
            try:
                result = LoadTestResult(**result)
            except ValidationError as e:
                logger.error(f"Failed to validate result as LoadTestResult: {e}")
                # Return a basic error result
                return LoadTestResult(
                    status="failed",
                    test_id=(
                        result.get("test_id", "unknown")
                        if isinstance(result, dict)
                        else "unknown"
                    ),
                    configuration=LoadTestConfiguration(
                        task_type=LoadTestTypes.CPU_INTENSIVE,  # Safe default enum
                        num_tasks=10,  # Minimum valid value
                        batch_size=1,
                        delay_ms=0,
                        target_queue="unknown",
                    ),
                    metrics=LoadTestMetrics(
                        tasks_sent=0,
                        tasks_completed=0,
                        tasks_failed=0,
                        total_duration_seconds=0.0,
                        overall_throughput=0.0,
                        failure_rate_percent=0.0,
                        completion_percentage=0.0,
                        average_throughput_per_second=0.0,
                        monitor_duration_seconds=0.0,
                    ),
                    start_time=None,
                    end_time=None,
                    error=f"Validation failed: {e}",
                    analysis=None,
                )

        # Verify result is LoadTestResult and handle unexpected types
        if not isinstance(result, LoadTestResult):
            logger.error(f"Expected LoadTestResult but got {type(result)}")
            return LoadTestResult(
                status="failed",
                test_id="unknown",
                configuration=LoadTestConfiguration(
                    task_type=LoadTestTypes.CPU_INTENSIVE,
                    num_tasks=10,
                    batch_size=1,
                    delay_ms=0,
                    target_queue="unknown",
                ),
                metrics=LoadTestMetrics(
                    tasks_sent=0,
                    tasks_completed=0,
                    tasks_failed=0,
                    total_duration_seconds=0.0,
                    overall_throughput=0.0,
                    failure_rate_percent=0.0,
                    completion_percentage=0.0,
                    average_throughput_per_second=0.0,
                    monitor_duration_seconds=0.0,
                ),
                start_time=None,
                end_time=None,
                error=f"Unexpected result type: {type(result)}",
                analysis=None,
            )

        task_type = result.configuration.task_type

        # Get expected characteristics for this test type
        # Validate task type against known types
        if task_type not in [
            LoadTestTypes.CPU_INTENSIVE,
            LoadTestTypes.IO_SIMULATION,
            LoadTestTypes.MEMORY_OPERATIONS,
            LoadTestTypes.FAILURE_TESTING,
        ]:
            task_type = LoadTestTypes.CPU_INTENSIVE  # Default fallback

        test_info_dict = AnalysisMixin.get_test_type_info(task_type)
        test_info = TestTypeInfo(**test_info_dict)

        # Create analysis components
        performance_analysis = AdviceMixin._analyze_performance_pydantic(result)
        validation_status = AdviceMixin._validate_test_execution_pydantic(
            result, test_info
        )
        recommendations = AdviceMixin._generate_recommendations_pydantic(result)

        # Add analysis to result
        from app.services.load_test.worker.models import LoadTestAnalysis

        analysis = LoadTestAnalysis(
            test_type_info=test_info,
            performance_analysis=performance_analysis,
            validation_status=validation_status,
            recommendations=recommendations,
        )

        result.analysis = analysis
        return result
