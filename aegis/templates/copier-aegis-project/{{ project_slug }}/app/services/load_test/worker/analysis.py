"""Reading a finished load test: what it was, and how it did."""

from typing import Any


from app.components.worker.constants import LoadTestTypes
from app.services.load_test.worker.advice import AdviceMixin
from app.services.load_test.worker.models import (
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
                    "One at a time per process, off the event loop: more processes, more at once"
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
    def _analyze_load_test_result(result: LoadTestResult) -> LoadTestResult:
        """Add analysis and validation to load test results."""
        task_type = result.configuration.task_type

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
