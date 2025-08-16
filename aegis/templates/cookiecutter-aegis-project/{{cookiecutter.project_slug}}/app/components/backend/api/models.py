"""
API models for background tasks and responses.

This module contains all Pydantic models used by the API layer for
task management, status tracking, and response formatting.
"""

from datetime import datetime
from typing import Dict, Any, Optional

from pydantic import BaseModel, Field


class TaskRequest(BaseModel):
    """Request model for enqueueing a background task."""

    task_name: str = Field(..., description="Name of the task function to execute")
    queue_type: str = Field(
        "system", description="Functional queue type: media or system"
    )
    args: list[Any] = Field(
        default_factory=list, description="Positional arguments for the task"
    )
    kwargs: Dict[str, Any] = Field(
        default_factory=dict, description="Keyword arguments for the task"
    )
    delay_seconds: Optional[int] = Field(
        None, description="Delay task execution by this many seconds"
    )


class TaskResponse(BaseModel):
    """Response model for task enqueue operations."""

    task_id: str
    task_name: str
    queue_type: str
    queued_at: datetime
    estimated_start: Optional[datetime] = None
    message: str


class TaskListResponse(BaseModel):
    """Response model for listing available tasks."""

    available_tasks: list[str]
    total_count: int
    queues: Dict[str, list[str]]


class TaskStatusResponse(BaseModel):
    """Response model for task status checks."""
    
    task_id: str
    status: str = Field(..., description="Task status: queued, in_progress, complete, failed, unknown")
    enqueue_time: Optional[datetime] = Field(None, description="When the task was enqueued")
    start_time: Optional[datetime] = Field(None, description="When the task started processing")
    finish_time: Optional[datetime] = Field(None, description="When the task completed")
    result_available: bool = Field(False, description="Whether task result is available")
    error: Optional[str] = Field(None, description="Error message if task failed")


class TaskResultResponse(BaseModel):
    """Response model for completed task results."""
    
    task_id: str
    status: str = Field(..., description="Task completion status")
    result: Any = Field(..., description="The actual task result data")
    enqueue_time: Optional[datetime] = Field(None, description="When the task was enqueued")
    start_time: Optional[datetime] = Field(None, description="When the task started processing")
    finish_time: Optional[datetime] = Field(None, description="When the task completed")


class LoadTestRequest(BaseModel):
    """Request model for orchestrating load tests that measure queue throughput."""
    
    num_tasks: int = Field(
        100, 
        description="Number of tasks to spawn for the load test",
        ge=10,
        le=10000
    )
    task_type: str = Field(
        "cpu_intensive", 
        description="Type of worker task to spawn for load testing",
        pattern="^(cpu_intensive|io_simulation|memory_operations|failure_testing)$"
    )
    batch_size: int = Field(
        10, 
        description="How many tasks to send concurrently per batch",
        ge=1,
        le=100
    )
    delay_ms: int = Field(
        0, 
        description="Delay between batches in milliseconds",
        ge=0,
        le=5000
    )
    target_queue: str = Field(
        "system", 
        description="Which queue to test (system or media)",
        pattern="^(system|media)$"
    )

    class Config:
        schema_extra = {
            "examples": [
                {
                    "description": "Quick CPU load test - fibonacci calculations and math operations",
                    "num_tasks": 50,
                    "task_type": "cpu_intensive", 
                    "batch_size": 10,
                    "delay_ms": 0,
                    "target_queue": "system",
                    "expected_work": "Computational: fibonacci, prime checking, mathematical operations",
                    "expected_metrics": ["fibonacci_result", "math_operations_sum", "operations_per_ms"]
                },
                {
                    "description": "I/O stress test - async operations and concurrent handling",
                    "num_tasks": 200,
                    "task_type": "io_simulation",
                    "batch_size": 20,
                    "delay_ms": 50,
                    "target_queue": "system",
                    "expected_work": "Async I/O: network delays, concurrent operations, file simulation",
                    "expected_metrics": ["concurrent_operations", "io_efficiency_percent", "concurrency_benefit"]
                },
                {
                    "description": "Memory allocation test - data structures and GC pressure",
                    "num_tasks": 500,
                    "task_type": "memory_operations",
                    "batch_size": 25,
                    "delay_ms": 0,
                    "target_queue": "media",
                    "expected_work": "Memory: allocation patterns, data manipulation, cleanup",
                    "expected_metrics": ["estimated_peak_memory_mb", "memory_throughput_mb_per_sec", "memory_operations_count"]
                },
                {
                    "description": "Failure resilience test - ~20% random failures for error handling",
                    "num_tasks": 100,
                    "task_type": "test_task_failure",
                    "batch_size": 15,
                    "delay_ms": 0,
                    "target_queue": "system",
                    "expected_work": "Failure testing: random errors, recovery patterns, resilience",
                    "expected_metrics": ["failure_roll", "failure_threshold", "would_have_failed"]
                }
            ]
        }


class LoadTestStatus(BaseModel):
    """Status model for monitoring active load tests."""
    
    test_id: str = Field(..., description="Unique load test identifier")
    status: str = Field(..., description="Test status: running, completed, failed")
    tasks_sent: int = Field(..., description="Number of tasks sent to queue")
    tasks_completed: int = Field(..., description="Number of tasks completed")
    tasks_failed: int = Field(0, description="Number of tasks that failed") 
    elapsed_seconds: float = Field(..., description="Time elapsed since test start")
    current_throughput: float = Field(..., description="Current tasks per second")
    estimated_completion: Optional[datetime] = Field(None, description="Estimated completion time")
    queue_depth: int = Field(0, description="Current queue depth")


class LoadTestResults(BaseModel):
    """Final results model for completed load tests."""
    
    test_id: str = Field(..., description="Unique load test identifier")
    status: str = Field(..., description="Final test status")
    configuration: LoadTestRequest = Field(..., description="Test configuration used")
    
    # Task metrics
    tasks_sent: int = Field(..., description="Total tasks sent")
    tasks_completed: int = Field(..., description="Total tasks completed")
    tasks_failed: int = Field(..., description="Total tasks failed")
    
    # Timing metrics
    start_time: datetime = Field(..., description="Test start time")
    end_time: Optional[datetime] = Field(None, description="Test end time")
    total_duration_seconds: float = Field(..., description="Total test duration")
    
    # Performance metrics
    overall_throughput: float = Field(..., description="Overall tasks per second")
    peak_throughput: float = Field(..., description="Peak throughput achieved")
    failure_rate: float = Field(..., description="Percentage of tasks that failed")
    
    # Queue metrics
    final_queue_metrics: Dict[str, Any] = Field(..., description="Final arq queue health data")
    
    # Summary
    performance_summary: str = Field(..., description="Human readable performance summary")