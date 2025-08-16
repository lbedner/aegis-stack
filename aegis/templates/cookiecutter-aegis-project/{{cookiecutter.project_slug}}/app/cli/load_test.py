"""
Load testing CLI commands.

Provides command-line interface for running and managing load tests,
with full parameter configuration and result analysis.
"""

import asyncio
from enum import Enum
import json
import time
from typing import Any

from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
import typer

from app.components.worker.constants import LoadTestTypes
from app.core.config import get_load_test_queue
from app.core.log import logger
from app.services.load_test import (
    LoadTestConfiguration,
    LoadTestService,
    quick_cpu_test,
    quick_io_test,
    quick_memory_test,
)

app = typer.Typer(
    name="load-test",
    help="Load testing commands for worker performance analysis",
    no_args_is_help=True,
)

console = Console()


class QueueChoice(str, Enum):
    """Available queue types for load testing."""
    load_test = "load_test"
    system = "system"  # Legacy option
    media = "media"    # Legacy option

    @classmethod
    def get_default(cls) -> str:
        """Get the default queue from config."""
        return get_load_test_queue()


@app.command("run")
def run_load_test(
    num_tasks: int = typer.Option(100, "--tasks", "-n", help="Number of tasks to spawn", min=10, max=10000),
    task_type: str = typer.Option(LoadTestTypes.CPU_INTENSIVE, "--type", "-t", help="Type of load test to run"),
    batch_size: int = typer.Option(10, "--batch", "-b", help="Tasks per batch", min=1, max=100),
    delay_ms: int = typer.Option(0, "--delay", "-d", help="Delay between batches (ms)", min=0, max=5000),
    target_queue: QueueChoice = typer.Option(QueueChoice.load_test, "--queue", "-q", help="Target queue for testing"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for test completion and show results"),
    timeout: int = typer.Option(600, "--timeout", help="Timeout for waiting (seconds)", min=10, max=3600),
) -> None:
    """
    Run a customizable load test with specified parameters.
    
    This command allows full control over load test configuration including
    task count, type, batching, and queue targeting.
    """

    config = LoadTestConfiguration(
        num_tasks=num_tasks,
        task_type=task_type,
        batch_size=batch_size,
        delay_ms=delay_ms,
        target_queue=target_queue.value
    )

    # Display test configuration
    _display_test_configuration(config, task_type)

    # Enqueue the load test
    rprint("🚀 [bold blue]Starting load test...[/bold blue]")

    try:
        task_id = asyncio.run(LoadTestService.enqueue_load_test(config))
        rprint("✅ [green]Load test enqueued successfully![/green]")
        rprint(f"📋 [cyan]Task ID:[/cyan] {task_id}")

        if wait:
            _wait_for_completion_and_display_results(task_id, target_queue.value, timeout)
        else:
            rprint("\n💡 [yellow]Use this command to check results later:[/yellow]")
            rprint(f"   [bold]full-stack load-test results {task_id}[/bold]")

    except Exception as e:
        rprint(f"❌ [red]Failed to start load test:[/red] {e}")
        raise typer.Exit(1)


@app.command("cpu")
def quick_cpu_test_cmd(
    num_tasks: int = typer.Option(50, "--tasks", "-n", help="Number of CPU tasks", min=10, max=1000),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for completion"),
) -> None:
    """
    Quick CPU-intensive load test with optimized defaults.
    
    Tests computational performance with fibonacci calculations,
    mathematical operations, and prime number checking.
    """

    rprint("🖥️  [bold blue]Quick CPU Load Test[/bold blue]")
    rprint(f"📊 [cyan]Tasks:[/cyan] {num_tasks} CPU-intensive tasks")
    rprint("🔢 [cyan]Work type:[/cyan] Fibonacci + math operations + prime checking")

    try:
        task_id = asyncio.run(quick_cpu_test(num_tasks))
        rprint(f"✅ [green]CPU test started![/green] Task ID: {task_id}")

        if wait:
            _wait_for_completion_and_display_results(task_id, get_load_test_queue(), 600)
        else:
            rprint(f"💡 [yellow]Check results:[/yellow] full-stack load-test results {task_id}")

    except Exception as e:
        rprint(f"❌ [red]CPU test failed:[/red] {e}")
        raise typer.Exit(1)


@app.command("io")
def quick_io_test_cmd(
    num_tasks: int = typer.Option(100, "--tasks", "-n", help="Number of I/O tasks", min=10, max=1000),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for completion"),
) -> None:
    """
    Quick I/O simulation load test with optimized defaults.
    
    Tests async I/O performance with simulated network delays,
    concurrent operations, and file I/O patterns.
    """

    rprint("💾 [bold blue]Quick I/O Load Test[/bold blue]")
    rprint(f"📊 [cyan]Tasks:[/cyan] {num_tasks} I/O simulation tasks")
    rprint("🌐 [cyan]Work type:[/cyan] Network delays + concurrent async + file operations")

    try:
        task_id = asyncio.run(quick_io_test(num_tasks))
        rprint(f"✅ [green]I/O test started![/green] Task ID: {task_id}")

        if wait:
            _wait_for_completion_and_display_results(task_id, get_load_test_queue(), 600)
        else:
            rprint(f"💡 [yellow]Check results:[/yellow] full-stack load-test results {task_id}")

    except Exception as e:
        rprint(f"❌ [red]I/O test failed:[/red] {e}")
        raise typer.Exit(1)


@app.command("memory")
def quick_memory_test_cmd(
    num_tasks: int = typer.Option(200, "--tasks", "-n", help="Number of memory tasks", min=10, max=1000),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for completion"),
) -> None:
    """
    Quick memory allocation load test with optimized defaults.
    
    Tests memory performance with data structure allocation,
    manipulation, and garbage collection patterns.
    """

    rprint("🧠 [bold blue]Quick Memory Load Test[/bold blue]")
    rprint(f"📊 [cyan]Tasks:[/cyan] {num_tasks} memory allocation tasks")
    rprint("📈 [cyan]Work type:[/cyan] Data structures + allocation patterns + GC testing")

    try:
        task_id = asyncio.run(quick_memory_test(num_tasks))
        rprint(f"✅ [green]Memory test started![/green] Task ID: {task_id}")

        if wait:
            _wait_for_completion_and_display_results(task_id, get_load_test_queue(), 600)
        else:
            rprint(f"💡 [yellow]Check results:[/yellow] full-stack load-test results {task_id}")

    except Exception as e:
        rprint(f"❌ [red]Memory test failed:[/red] {e}")
        raise typer.Exit(1)


@app.command("results")
def show_results(
    task_id: str = typer.Argument(..., help="Load test task ID"),
    target_queue: QueueChoice = typer.Option(QueueChoice.system, "--queue", "-q", help="Queue where test was run"),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed analysis and metrics"),
    json_output: bool = typer.Option(False, "--json", help="Output results in JSON format"),
) -> None:
    """
    Display results and analysis for a completed load test.
    
    Retrieves and analyzes load test results, showing performance metrics,
    test type verification, and recommendations.
    """

    try:
        result = asyncio.run(LoadTestService.get_load_test_result(task_id, target_queue.value))

        if not result:
            rprint(f"❌ [red]No results found for task ID:[/red] {task_id}")
            rprint("💡 [yellow]Check that the task ID is correct and the test has completed[/yellow]")
            raise typer.Exit(1)

        if json_output:
            print(json.dumps(result, indent=2, default=str))
            return

        _display_load_test_results(result, detailed)

    except Exception as e:
        rprint(f"❌ [red]Failed to retrieve results:[/red] {e}")
        raise typer.Exit(1)


@app.command("info")
def show_test_type_info(
    test_type: str | None = typer.Argument(None, help="Specific test type to show info for"),
) -> None:
    """
    Display information about available load test types and their characteristics.
    
    Shows what each test type does, expected performance signatures,
    and guidance for choosing the right test for your needs.
    """

    if test_type:
        # Show detailed info for specific test type
        info = LoadTestService.get_test_type_info(test_type)
        _display_test_type_info(test_type, info)
    else:
        # Show overview of all test types
        rprint("🧪 [bold blue]Available Load Test Types[/bold blue]\n")

        for test_type in [LoadTestTypes.CPU_INTENSIVE, LoadTestTypes.IO_SIMULATION, LoadTestTypes.MEMORY_OPERATIONS, LoadTestTypes.FAILURE_TESTING]:
            info = LoadTestService.get_test_type_info(test_type)
            rprint(f"🔹 [bold cyan]{test_type}[/bold cyan] - {info.get('name', 'Unknown')}")
            rprint(f"   {info.get('description', 'No description available')}")
            rprint(f"   [dim]Typical duration: {info.get('typical_duration_ms', 'Unknown')}[/dim]\n")

        rprint("💡 [yellow]Use --help with specific commands for more details[/yellow]")
        rprint("📖 [cyan]Examples:[/cyan]")
        rprint("   full-stack load-test info cpu_intensive")
        rprint("   full-stack load-test info io_simulation")
        rprint("   full-stack load-test info memory_operations")


def _display_test_configuration(config: LoadTestConfiguration, test_type: str) -> None:
    """Display load test configuration in a formatted panel."""

    test_info = LoadTestService.get_test_type_info(test_type)

    config_text = f"""
[bold cyan]Test Configuration[/bold cyan]

🔢 [cyan]Tasks:[/cyan] {config.num_tasks} {test_type} tasks
📦 [cyan]Batching:[/cyan] {config.batch_size} tasks per batch
⏱️  [cyan]Delay:[/cyan] {config.delay_ms}ms between batches  
🎯 [cyan]Queue:[/cyan] {config.target_queue}

[bold yellow]Test Type Details[/bold yellow]
📋 [yellow]Name:[/yellow] {test_info.get('name', 'Unknown')}
📝 [yellow]Description:[/yellow] {test_info.get('description', 'No description')}
⚡ [yellow]Performance:[/yellow] {test_info.get('performance_signature', 'Unknown')}
🏃 [yellow]Concurrency:[/yellow] {test_info.get('concurrency_impact', 'Unknown')}
    """.strip()

    console.print(Panel(config_text, title="🚀 Load Test Setup", border_style="blue"))


def _display_test_type_info(test_type: str, info: dict[str, Any]) -> None:
    """Display detailed information about a specific test type."""

    info_text = f"""
[bold cyan]{info.get('name', 'Unknown Test Type')}[/bold cyan]

[bold yellow]Description[/bold yellow]
{info.get('description', 'No description available')}

[bold yellow]Performance Characteristics[/bold yellow]
🔍 [yellow]Signature:[/yellow] {info.get('performance_signature', 'Unknown')}
⏱️  [yellow]Duration:[/yellow] {info.get('typical_duration_ms', 'Unknown')}
🔄 [yellow]Concurrency:[/yellow] {info.get('concurrency_impact', 'Unknown')}

[bold yellow]Expected Metrics[/bold yellow]
📊 {', '.join(info.get('expected_metrics', ['No metrics specified']))}

[bold yellow]Validation Keys[/bold yellow]
🔑 {', '.join(info.get('validation_keys', ['No validation keys']))}
    """.strip()

    console.print(Panel(info_text, title=f"🧪 {test_type} Test Type", border_style="green"))


def _wait_for_completion_and_display_results(task_id: str, target_queue: str, timeout: int) -> None:
    """Wait for load test completion and display results."""

    rprint(f"\n⏳ [yellow]Waiting for load test completion (timeout: {timeout}s)...[/yellow]")

    start_time = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:

        wait_task = progress.add_task("Waiting for load test to complete...", total=None)

        while True:
            elapsed = time.time() - start_time

            if elapsed > timeout:
                progress.update(wait_task, description="❌ Timeout reached")
                rprint(f"\n⏰ [red]Timeout reached after {timeout}s[/red]")
                rprint(f"💡 [yellow]Check results manually:[/yellow] full-stack load-test results {task_id}")
                return

            try:
                result = asyncio.run(LoadTestService.get_load_test_result(task_id, target_queue))

                if result:
                    progress.update(wait_task, description="✅ Load test completed!")
                    break

            except Exception as e:
                logger.debug(f"Error checking results: {e}")

            # Update progress description with elapsed time
            progress.update(wait_task, description=f"Waiting for completion... ({elapsed:.1f}s)")
            time.sleep(2)

    rprint("\n🎉 [bold green]Load test completed![/bold green]")
    _display_load_test_results(result, detailed=True)


def _display_load_test_results(result: dict[str, Any], detailed: bool = False) -> None:
    """Display formatted load test results."""

    # Basic results
    status = result.get("status", "unknown")
    test_id = result.get("test_id", "unknown")

    # Handle timeout and failure cases
    if status in ["timed_out", "failed"]:
        _display_error_result(result, status)
        return

    # Handle successful results
    config = result.get("configuration", {})
    metrics = result.get("metrics", {})

    # Create summary table for successful results
    table = Table(title="📊 Load Test Results Summary", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")
    table.add_column("Details", style="dim")

    # Add basic metrics
    table.add_row("Status", status, "Test execution status")
    table.add_row("Tasks Sent", str(metrics.get("tasks_sent", "unknown")), "Total tasks enqueued")
    table.add_row("Tasks Completed", str(metrics.get("tasks_completed", "unknown")), "Successfully completed")
    table.add_row("Tasks Failed", str(metrics.get("tasks_failed", "unknown")), "Failed during execution")
    table.add_row("Duration", f"{metrics.get('total_duration_seconds', 0):.2f}s", "Total test duration")
    table.add_row("Throughput", f"{metrics.get('overall_throughput', 0):.2f} tasks/sec", "Average task completion rate")
    table.add_row("Failure Rate", f"{metrics.get('failure_rate_percent', 0):.1f}%", "Percentage of failed tasks")

    console.print(table)

    # Show performance analysis if available
    analysis = result.get("analysis", {})
    if analysis and detailed:
        _display_performance_analysis(analysis)

    # Show performance summary
    perf_summary = result.get("performance_summary", "No summary available")
    console.print("\n💡 [bold yellow]Performance Summary[/bold yellow]")
    console.print(f"   {perf_summary}")

    # Show recommendations if available
    recommendations = analysis.get("recommendations", []) if analysis else []
    if recommendations:
        console.print("\n🔧 [bold blue]Recommendations[/bold blue]")
        for i, rec in enumerate(recommendations, 1):
            console.print(f"   {i}. {rec}")


def _display_error_result(result: dict[str, Any], status: str) -> None:
    """Display results for failed or timed out load tests."""

    test_id = result.get("test_id", "unknown")
    error = result.get("error", "Unknown error")
    partial_info = result.get("partial_info", "")

    if status == "timed_out":
        console.print(Panel(
            f"[bold red]⏰ Load Test Timed Out[/bold red]\n\n"
            f"[cyan]Test ID:[/cyan] {test_id}\n"
            f"[cyan]Error:[/cyan] {error}\n\n"
            f"[yellow]What this means:[/yellow]\n"
            f"The orchestrator task timed out, but individual worker tasks may have completed successfully.\n"
            f"This often happens with large load tests that exceed the queue timeout.\n\n"
            f"[blue]To investigate:[/blue]\n"
            f"• Check worker logs for individual task completion\n"
            f"• Consider using smaller batch sizes for large tests\n"
            f"• Check queue metrics for actual task completion counts",
            title="🔍 Load Test Analysis",
            border_style="red"
        ))

        if partial_info:
            console.print(f"\n📝 [dim]{partial_info}[/dim]")

    elif status == "failed":
        console.print(Panel(
            f"[bold red]❌ Load Test Failed[/bold red]\n\n"
            f"[cyan]Test ID:[/cyan] {test_id}\n"
            f"[cyan]Error:[/cyan] {error}\n\n"
            f"[blue]Next steps:[/blue]\n"
            f"• Check worker logs for detailed error information\n"
            f"• Verify queue connectivity and worker status\n"
            f"• Try a smaller test to isolate the issue",
            title="🔍 Load Test Analysis",
            border_style="red"
        ))

    # Show basic troubleshooting info
    console.print("\n💡 [bold yellow]Troubleshooting Tips[/bold yellow]")
    console.print("   1. Check worker container logs: docker compose logs worker")
    console.print("   2. Verify system health: full-stack health check")
    console.print("   3. Try a smaller load test first: full-stack load-test cpu --tasks 10")


def _display_performance_analysis(analysis: dict[str, Any]) -> None:
    """Display detailed performance analysis."""

    perf_analysis = analysis.get("performance_analysis", {})
    validation = analysis.get("validation_status", {})
    test_info = analysis.get("test_type_info", {})

    # Performance ratings table
    perf_table = Table(title="🎯 Performance Analysis", show_header=True, header_style="bold blue")
    perf_table.add_column("Aspect", style="cyan")
    perf_table.add_column("Rating", style="bold")
    perf_table.add_column("Description", style="dim")

    # Add performance ratings with color coding
    throughput_rating = perf_analysis.get("throughput_rating", "unknown")
    throughput_color = _get_rating_color(throughput_rating)
    perf_table.add_row("Throughput", f"[{throughput_color}]{throughput_rating}[/{throughput_color}]", "Task processing speed")

    efficiency_rating = perf_analysis.get("efficiency_rating", "unknown")
    efficiency_color = _get_rating_color(efficiency_rating)
    perf_table.add_row("Efficiency", f"[{efficiency_color}]{efficiency_rating}[/{efficiency_color}]", "Task completion rate")

    queue_pressure = perf_analysis.get("queue_pressure", "unknown")
    pressure_color = "red" if queue_pressure == "high" else "yellow" if queue_pressure == "medium" else "green"
    perf_table.add_row("Queue Pressure", f"[{pressure_color}]{queue_pressure}[/{pressure_color}]", "Queue saturation level")

    console.print(perf_table)

    # Validation status
    if validation:
        console.print("\n✅ [bold green]Test Validation[/bold green]")
        console.print(f"   🔍 Test type verified: {validation.get('test_type_verified', 'unknown')}")
        console.print(f"   📊 Expected metrics present: {validation.get('expected_metrics_present', 'unknown')}")
        console.print(f"   📈 Performance signature match: {validation.get('performance_signature_match', 'unknown')}")


def _get_rating_color(rating: str) -> str:
    """Get color for performance rating."""
    color_map = {
        "excellent": "green",
        "good": "blue",
        "fair": "yellow",
        "poor": "red",
        "unknown": "dim"
    }
    return color_map.get(rating, "dim")


if __name__ == "__main__":
    app()
