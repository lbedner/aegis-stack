"""
Lightweight worker tasks for load testing.

These tasks are designed to be spawned in large numbers to test queue throughput
and worker performance. Each task does minimal work to focus on testing the
infrastructure rather than computational complexity.
"""

import asyncio
from datetime import datetime
import random
from typing import Any

from app.core.log import logger


async def cpu_intensive_task(ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    CPU-intensive load testing task.

    Performs realistic computational work including hash calculations, sorting,
    and mathematical operations to test worker CPU processing capabilities.
    Designed to actually use CPU cycles and test computational throughput.

    Returns:
        Task completion data with CPU-specific metrics and verification data
    """
    start_time = datetime.now()
    task_id = ctx.get("job_id", "unknown")

    # CPU work 1: Fibonacci calculation (larger numbers for real work)
    n = random.randint(500, 1500)  # Much larger range for actual CPU work
    a, b = 0, 1
    operations_count = 0

    for i in range(n):
        a, b = b, a + b
        operations_count += 1

    # CPU work 2: Sorting random data (CPU intensive)
    data_size = random.randint(1000, 3000)
    random_data = [random.randint(1, 10000) for _ in range(data_size)]
    sorted_data = sorted(random_data)
    operations_count += data_size  # Approximate operations for sorting

    # CPU work 3: Hash calculations (CPU intensive)
    import hashlib

    hash_operations = random.randint(50, 150)
    hash_results = []
    for i in range(hash_operations):
        data_to_hash = f"load_test_data_{i}_{random.randint(1, 100000)}"
        hash_result = hashlib.sha256(data_to_hash.encode()).hexdigest()
        hash_results.append(hash_result[:8])  # Store first 8 chars
        operations_count += 1

    # CPU work 4: Mathematical computations
    math_iterations = random.randint(5000, 15000)
    math_result = 0
    for i in range(math_iterations):
        # More complex math operations
        math_result += (i**2 + i**0.5) * 0.1
        operations_count += 1

    # CPU work 5: Prime number generation (CPU bound)
    prime_start = random.randint(1000, 2000)
    primes_found: list[int] = []
    num = prime_start
    while len(primes_found) < 20:  # Find 20 primes
        is_prime = True
        if num > 1:
            for i in range(2, int(num**0.5) + 1):
                operations_count += 1
                if num % i == 0:
                    is_prime = False
                    break
        else:
            is_prime = False

        if is_prime:
            primes_found.append(num)
        num += 1

    # CPU work 6: Simulate encoding/image processing (realistic CPU-heavy work)
    encoding_operations = 0
    # Simulate image/video encoding by doing intensive matrix operations
    for frame in range(random.randint(10, 30)):  # Process "frames"
        # Simulate encoding a frame with matrix multiplication
        matrix_size = random.randint(50, 100)
        matrix_a = [
            [random.random() for _ in range(matrix_size)] for _ in range(matrix_size)
        ]
        matrix_b = [
            [random.random() for _ in range(matrix_size)] for _ in range(matrix_size)
        ]

        # Matrix multiplication (very CPU intensive)
        result_matrix = [[0.0 for _ in range(matrix_size)] for _ in range(matrix_size)]
        for i in range(matrix_size):
            for j in range(matrix_size):
                for k in range(matrix_size):
                    result_matrix[i][j] += matrix_a[i][k] * matrix_b[k][j]
                    encoding_operations += 1

    # WARNING: This blocks the entire async event loop!
    # In real systems, this would prevent other async tasks from running
    event_loop_warning = "CPU work blocks async event loop - other tasks must wait!"

    end_time = datetime.now()
    duration_ms = (end_time - start_time).total_seconds() * 1000

    return {
        "task_type": "cpu_intensive",
        "task_id": task_id,
        # CPU work proof
        "fibonacci_n": n,
        "fibonacci_result": str(b)[:10] + "..." if len(str(b)) > 10 else str(b),
        "sorted_data_size": len(sorted_data),
        "hash_operations": hash_operations,
        "hash_sample": hash_results[:3],  # First 3 hashes as proof
        "math_iterations": math_iterations,
        "math_result": round(math_result, 2),
        "primes_found": primes_found,
        "encoding_operations": encoding_operations,
        "total_cpu_operations": operations_count + encoding_operations,
        # Performance metrics
        "duration_ms": round(duration_ms, 2),
        "operations_per_ms": round(
            (operations_count + encoding_operations) / max(duration_ms, 0.001), 2
        ),
        "cpu_intensive_score": round(
            (operations_count + encoding_operations) / max(duration_ms / 1000, 0.001), 0
        ),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        # Async event loop impact
        "async_event_loop_blocked_ms": round(duration_ms, 2),
        "event_loop_warning": event_loop_warning,
        "concurrency_impact": "HIGH - Blocks entire event loop during execution",
        # Verification signature
        "work_type": "CPU_COMPUTATION_WITH_ENCODING",
        "verification": f"fib({n}), sort({data_size}), hash({hash_operations}), "
        f"math({math_iterations}), primes({len(primes_found)}), "
        f"encoding({encoding_operations}ops)",
        "status": "completed",
    }


async def io_simulation_task(ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    I/O-intensive load testing task optimized for high throughput.

    Simulates realistic async I/O patterns with minimal delays to avoid queue
    saturation while still demonstrating async concurrency benefits. Focuses on
    async pattern demonstration rather than realistic I/O timing.

    Returns:
        Task completion data with I/O-specific metrics and concurrency analysis
    """
    start_time = datetime.now()
    task_id = ctx.get("job_id", "unknown")

    # Ultra-lightweight I/O simulation to prevent queue saturation
    # Focus on async patterns with minimal actual delays

    async def simulate_database_read(read_id: int) -> dict[str, Any]:
        """Simulate a database read with ultra-minimal delay."""
        op_start = datetime.now()
        # Extremely short delay to show async pattern without queue buildup
        await asyncio.sleep(0.001)  # 1ms max
        op_end = datetime.now()
        return {
            "operation_id": read_id,
            "operation_type": "database_read",
            "table": f"users_{read_id}",
            "simulated_delay_ms": 1,
            "actual_duration_ms": round((op_end - op_start).total_seconds() * 1000, 3),
            "rows_returned": random.randint(10, 100),
        }

    async def simulate_api_call(api_id: int) -> dict[str, Any]:
        """Simulate an external API call with ultra-minimal delay."""
        op_start = datetime.now()
        # Minimal async yield to demonstrate concurrency
        await asyncio.sleep(0.001)  # 1ms max
        op_end = datetime.now()
        return {
            "operation_id": api_id,
            "operation_type": "api_call",
            "endpoint": f"/api/data/{api_id}",
            "simulated_delay_ms": 1,
            "actual_duration_ms": round((op_end - op_start).total_seconds() * 1000, 3),
            "status_code": random.choice([200, 200, 200, 201, 404]),
        }

    async def simulate_cache_read(cache_id: int) -> dict[str, Any]:
        """Simulate a cache read operation (very fast)."""
        op_start = datetime.now()
        # Cache should be fastest - just yield control
        await asyncio.sleep(0.0005)  # 0.5ms max
        op_end = datetime.now()
        return {
            "operation_id": cache_id,
            "operation_type": "cache_read",
            "cache_key": f"user_session_{cache_id}",
            "simulated_delay_ms": 0.5,
            "actual_duration_ms": round((op_end - op_start).total_seconds() * 1000, 3),
            "cache_hit": random.choice([True, True, True, False]),  # Mostly hits
        }

    # Fewer concurrent operations to reduce total time
    db_tasks = [simulate_database_read(i) for i in range(2)]
    api_tasks = [simulate_api_call(i) for i in range(2)]
    cache_tasks = [simulate_cache_read(i) for i in range(3)]

    # Execute all I/O operations concurrently (key async benefit)
    concurrent_ops_start = datetime.now()
    all_operations = await asyncio.gather(*db_tasks, *api_tasks, *cache_tasks)
    concurrent_ops_end = datetime.now()
    concurrent_duration = (
        concurrent_ops_end - concurrent_ops_start
    ).total_seconds() * 1000

    # Light data processing (realistic for I/O workloads)
    processing_start = datetime.now()

    # Aggregate results (typical I/O task post-processing)
    success_count = 0
    error_count = 0
    total_rows = 0
    cache_hits = 0

    for op in all_operations:
        if op["operation_type"] == "database_read":
            total_rows += op["rows_returned"]
            success_count += 1
        elif op["operation_type"] == "api_call":
            if op["status_code"] in [200, 201]:
                success_count += 1
            else:
                error_count += 1
        elif op["operation_type"] == "cache_read":
            if op["cache_hit"]:
                cache_hits += 1
            success_count += 1

    processing_end = datetime.now()
    processing_duration = (processing_end - processing_start).total_seconds() * 1000

    end_time = datetime.now()
    total_duration_ms = (end_time - start_time).total_seconds() * 1000

    # Calculate async concurrency benefits
    total_simulated_delay = sum(op["simulated_delay_ms"] for op in all_operations)
    actual_concurrent_time = concurrent_duration
    concurrency_factor = total_simulated_delay / max(actual_concurrent_time, 0.001)
    time_saved_ms = total_simulated_delay - actual_concurrent_time

    # Categorize operations by type
    db_operations = [
        op for op in all_operations if op["operation_type"] == "database_read"
    ]
    api_operations = [op for op in all_operations if op["operation_type"] == "api_call"]
    cache_operations = [
        op for op in all_operations if op["operation_type"] == "cache_read"
    ]

    return {
        "task_type": "io_simulation",
        "task_id": task_id,
        # I/O work proof and results
        "database_operations": len(db_operations),
        "api_operations": len(api_operations),
        "cache_operations": len(cache_operations),
        "total_concurrent_operations": len(all_operations),
        "processing_results": {
            "total_rows_processed": total_rows,
            "success_operations": success_count,
            "error_operations": error_count,
            "cache_hits": cache_hits,
        },
        # Performance and concurrency metrics
        "total_duration_ms": round(total_duration_ms, 3),
        "concurrent_io_duration_ms": round(concurrent_duration, 3),
        "processing_duration_ms": round(processing_duration, 3),
        "total_simulated_delay_ms": total_simulated_delay,
        "concurrency_time_saved_ms": round(time_saved_ms, 3),
        "concurrency_factor": round(concurrency_factor, 2),
        "io_throughput_ops_per_sec": round(
            len(all_operations) / max(total_duration_ms / 1000, 0.001), 1
        ),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        # Async pattern demonstration
        "async_pattern_demo": {
            "sequential_would_take_ms": total_simulated_delay,
            "concurrent_actual_ms": round(concurrent_duration, 3),
            "efficiency_improvement": (
                f"{round((time_saved_ms / total_simulated_delay) * 100, 1)}%"
                if total_simulated_delay > 0
                else "0%"
            ),
        },
        # Verification signature
        "work_type": "OPTIMIZED_ASYNC_IO",
        "verification": (
            f"concurrent({len(all_operations)}ops, "
            f"{total_simulated_delay}ms→{round(concurrent_duration, 1)}ms, "
            f"{round(concurrency_factor, 1)}x speedup)"
        ),
        "status": "completed",
    }


async def memory_operations_task(ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    Memory-intensive load testing task with allocation patterns.

    Performs realistic memory allocation, manipulation, and deallocation
    patterns to test worker memory handling, garbage collection impact,
    and memory bandwidth utilization.

    Returns:
        Task completion data with memory-specific metrics and allocation details
    """
    start_time = datetime.now()
    task_id = ctx.get("job_id", "unknown")

    # Memory allocation pattern 1: Sequential data structures
    list_size = random.randint(500, 2000)  # Larger for better measurement
    data_list = list(range(list_size))

    # Memory allocation pattern 2: Dictionary with string values
    dict_size = list_size // 4
    data_dict = {i: f"memory_test_value_{i}_{'x' * 10}" for i in range(dict_size)}

    # Memory allocation pattern 3: Nested structures
    nested_data = []
    for i in range(50):
        nested_item = {
            "id": i,
            "data": [j * 2 for j in range(20)],
            "metadata": {"created": datetime.now().isoformat(), "size": 20},
        }
        nested_data.append(nested_item)

    # Memory operations: processing that causes memory access patterns
    # List operations
    list_sum = sum(data_list)
    list_squares = [x**2 for x in data_list[:100]]  # Limited to avoid excessive memory
    max_value = max(data_list) if data_list else 0
    min_value = min(data_list) if data_list else 0

    # Dictionary operations
    dict_keys_count = len(data_dict)
    dict_values_total_len = sum(len(v) for v in data_dict.values())

    # Nested data processing  
    nested_sum = sum(sum(item["data"]) for item in nested_data)  # type: ignore[call-overload]
    nested_items_count = len(nested_data)

    # Memory churn: create and destroy temporary objects
    temp_objects = []
    for i in range(100):
        temp_obj = {"temp_id": i, "temp_data": list(range(10))}
        temp_objects.append(temp_obj)

    # Process temp objects then clean up
    temp_sum = sum(sum(obj["temp_data"]) for obj in temp_objects)  # type: ignore[call-overload]
    del temp_objects  # Explicit cleanup

    # Calculate memory usage estimates (approximate)
    estimated_list_bytes = list_size * 8  # Rough estimate for integers
    estimated_dict_bytes = dict_size * (8 + 30)  # Key + average string length
    estimated_nested_bytes = len(nested_data) * 200  # Rough estimate
    total_estimated_bytes = (
        estimated_list_bytes + estimated_dict_bytes + estimated_nested_bytes
    )

    # Clean up main data structures
    del data_list
    del data_dict
    del nested_data

    end_time = datetime.now()
    duration_ms = (end_time - start_time).total_seconds() * 1000

    return {
        "task_type": "memory_operations",
        "task_id": task_id,
        # Memory work proof
        "list_allocation_size": list_size,
        "dict_allocation_size": dict_size,
        "nested_structures_count": nested_items_count,
        "temp_objects_processed": 100,
        # Memory operation results
        "list_sum": list_sum,
        "list_squares_sample": len(list_squares),
        "max_value": max_value,
        "min_value": min_value,
        "dict_keys_count": dict_keys_count,
        "dict_values_total_length": dict_values_total_len,
        "nested_sum": nested_sum,
        "temp_sum": temp_sum,
        # Memory metrics
        "estimated_peak_memory_bytes": total_estimated_bytes,
        "estimated_peak_memory_mb": round(total_estimated_bytes / (1024 * 1024), 2),
        "memory_operations_count": 8,  # Major allocation/processing operations
        "duration_ms": round(duration_ms, 2),
        "memory_throughput_mb_per_sec": round(
            (total_estimated_bytes / (1024 * 1024)) / max(duration_ms / 1000, 0.001), 2
        ),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        # Verification signature
        "work_type": "MEMORY_ALLOCATION",
        "verification": (
            f"list({list_size}) + dict({dict_size}) + "
            f"nested({nested_items_count}) + temp(100) = {total_estimated_bytes}bytes"
        ),
        "status": "completed",
    }


async def failure_testing_task(ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    Failure testing task for error handling validation.

    Randomly fails ~20% of the time to test worker resilience,
    error handling, and failure recovery patterns. When successful,
    provides minimal work to focus on failure testing.

    Returns:
        Task completion data with failure testing metrics
    """
    start_time = datetime.now()
    task_id = ctx.get("job_id", "unknown")

    # Random failure probability (20%)
    failure_roll = random.random()
    failure_threshold = 0.2

    # Generate different types of failures for testing
    if failure_roll < failure_threshold:
        failure_types = [
            "simulated_network_timeout",
            "simulated_database_error",
            "simulated_validation_error",
            "simulated_resource_exhaustion",
            "simulated_permission_error",
        ]

        failure_type = random.choice(failure_types)
        error_message = (
            f"Simulated {failure_type} for resilience testing "
            f"(task {task_id}, roll={failure_roll:.3f})"
        )

        # Log failure details before raising
        logger.warning(f"🧪 Intentional test failure: {error_message}")

        raise Exception(error_message)

    # Success path: minimal work with timing
    work_type = random.choice(["quick_sleep", "light_calculation", "simple_operation"])

    if work_type == "quick_sleep":
        delay_ms = random.randint(5, 15)
        await asyncio.sleep(delay_ms / 1000)
        work_detail = f"sleep({delay_ms}ms)"

    elif work_type == "light_calculation":
        n = random.randint(5, 15)
        result = sum(i**2 for i in range(n))
        work_detail = f"sum_squares({n})={result}"

    else:  # simple_operation
        data = [i for i in range(10)]
        result = len(data) + sum(data)
        work_detail = f"list_ops({len(data)})={result}"

    end_time = datetime.now()
    duration_ms = (end_time - start_time).total_seconds() * 1000

    return {
        "task_type": "failure_testing",
        "task_id": task_id,
        # Failure testing proof
        "failure_roll": round(failure_roll, 3),
        "failure_threshold": failure_threshold,
        "would_have_failed": failure_roll < failure_threshold,
        "success_work_type": work_type,
        "work_detail": work_detail,
        # Performance metrics
        "duration_ms": round(duration_ms, 2),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        # Verification signature
        "work_type": "FAILURE_TESTING",
        "verification": (
            f"roll={failure_roll:.3f} < {failure_threshold} = "
            f"{failure_roll < failure_threshold}, work={work_detail}"
        ),
        "status": "completed",
    }
