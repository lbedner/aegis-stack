"""Back-compat shim for ``app.services.load_test_models``.

Models moved to ``app.services.load_test.worker.models`` when the load-test
service was restructured into a package. This shim keeps existing imports
working without forcing callsite changes.
"""

from app.services.load_test.worker.models import (
    LoadTestAnalysis,
    LoadTestConfiguration,
    LoadTestMetrics,
    LoadTestResult,
    OrchestratorRawResult,
    PerformanceAnalysis,
    TestTypeInfo,
    ValidationStatus,
)

__all__ = [
    "LoadTestAnalysis",
    "LoadTestConfiguration",
    "LoadTestMetrics",
    "LoadTestResult",
    "OrchestratorRawResult",
    "PerformanceAnalysis",
    "TestTypeInfo",
    "ValidationStatus",
]
