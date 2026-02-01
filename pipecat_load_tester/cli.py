"""CLI entry point for load testing."""
import asyncio
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.logging import RichHandler
from rich.panel import Panel

from .audio import AudioGenerator
from .metrics import MetricsCollector
from .orchestrator import LoadOrchestrator
from .config import PipecatConfig, get_config

console = Console()
logger = logging.getLogger("pipecat_load_tester")


def setup_logging(verbose: bool, log_level: str = "INFO"):
    """Configure logging with rich handler."""
    level = logging.DEBUG if verbose else getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)]
    )


def validate_config(config: PipecatConfig) -> bool:
    """Validate config and print errors if any."""
    errors = config.validate()
    if errors:
        console.print("[bold red]Configuration errors:[/bold red]")
        for error in errors:
            console.print(f"  [red]• {error}[/red]")
        return False
    return True


def print_banner(test_type: str, config: PipecatConfig, **kwargs):
    """Print test banner with configuration."""
    lines = [
        f"[bold cyan]Pipecat Load Test - {test_type}[/bold cyan]",
        "",
        f"[dim]Host:[/dim] {config.host}",
    ]

    for key, value in kwargs.items():
        display_key = key.replace('_', ' ').title()
        lines.append(f"[dim]{display_key}:[/dim] {value}")

    if config.audio_file:
        lines.append(f"[dim]Audio:[/dim] {config.audio_file}")
    else:
        lines.append(f"[dim]Audio:[/dim] synthetic sine wave ({config.default_audio_frequency}Hz)")

    console.print(Panel("\n".join(lines), border_style="cyan"))


@click.group()
@click.option('--config', '-c', 'config_path', default=None, help='Path to YAML config file')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose/debug output')
@click.pass_context
def cli(ctx, config_path, verbose):
    """Pipecat Load Testing Tool

    A load testing tool for Pipecat voice bots with RTVI protocol support.

    Examples:

        # Quick test with defaults
        pipecat-load-test sustained

        # Custom host and connections
        pipecat-load-test sustained --host myserver:8000 -n 50

        # Use config file
        pipecat-load-test -c config.yaml sustained

        # Ramp up test
        pipecat-load-test ramp --start 10 --end 100 --step 10
    """
    ctx.ensure_object(dict)

    # Load config
    config = get_config(config_path)
    ctx.obj['config'] = config
    ctx.obj['verbose'] = verbose

    # Setup logging
    setup_logging(verbose, config.log_level)


@cli.command()
@click.option('--host', '-h', default=None, help='Server host:port (default: localhost:8000)')
@click.option('--connections', '-n', default=None, type=int, help='Number of concurrent connections (default: 10)')
@click.option('--duration', '-d', default=None, type=int, help='Test duration in seconds (default: 60)')
@click.option('--audio', '-a', default=None, help='Path to audio file (.wav). Uses synthetic if not provided.')
@click.option('--output', '-o', default=None, help='Output metrics file (default: results.json)')
@click.pass_context
def sustained(ctx, host, connections, duration, audio, output):
    """Run sustained load test with N connections for D seconds.

    This test maintains a constant number of concurrent connections
    for the specified duration, simulating steady-state load.

    Examples:

        # 10 connections for 60 seconds (defaults)
        pipecat-load-test sustained

        # 50 connections for 5 minutes
        pipecat-load-test sustained -n 50 -d 300

        # With custom audio file
        pipecat-load-test sustained -a samples/greeting.wav
    """
    config = ctx.obj['config']
    verbose = ctx.obj['verbose']

    # Override config with CLI args
    if host:
        config.host = host
    if audio:
        config.audio_file = audio
    connections = connections or config.default_connections
    duration = duration or config.default_duration
    output = output or config.default_output

    if not validate_config(config):
        sys.exit(1)

    print_banner("Sustained", config, connections=connections, duration=f"{duration}s")

    try:
        asyncio.run(_run_sustained(config, connections, duration, output, verbose))
    except KeyboardInterrupt:
        console.print("\n[yellow]Test interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[bold red]Test failed:[/bold red] {e}")
        if verbose:
            console.print_exception()
        sys.exit(1)


async def _run_sustained(config: PipecatConfig, connections: int, duration: int, output: str, verbose: bool):
    audio_gen = AudioGenerator(config.audio_file) if config.audio_file else AudioGenerator()
    metrics = MetricsCollector()
    orchestrator = LoadOrchestrator(config.host, audio_gen, metrics, config=config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[cyan]Running {connections} connections...",
            total=duration
        )

        # Run the test with progress updates
        await orchestrator.run_sustained(connections, duration, progress_callback=lambda elapsed: progress.update(task, completed=elapsed))

    metrics.print_summary()
    metrics.save_report(output)
    console.print(f"\n[green]✓ Results saved to {output}[/green]")


@cli.command()
@click.option('--host', '-h', default=None, help='Server host:port')
@click.option('--start', default=10, help='Starting connections (default: 10)')
@click.option('--end', default=100, help='Ending connections (default: 100)')
@click.option('--step', default=10, help='Increment step (default: 10)')
@click.option('--interval', default=30, help='Seconds between steps (default: 30)')
@click.option('--audio', '-a', default=None, help='Path to audio file')
@click.option('--output', '-o', default=None, help='Output metrics file')
@click.pass_context
def ramp(ctx, host, start, end, step, interval, audio, output):
    """Run ramp-up load test: gradually increase connections.

    This test starts with a small number of connections and gradually
    increases to find the breaking point or maximum capacity.

    Examples:

        # Ramp from 10 to 100 connections
        pipecat-load-test ramp --start 10 --end 100

        # Slower ramp with longer intervals
        pipecat-load-test ramp --start 5 --end 50 --step 5 --interval 60
    """
    config = ctx.obj['config']
    verbose = ctx.obj['verbose']

    if host:
        config.host = host
    if audio:
        config.audio_file = audio
    output = output or config.default_output

    if not validate_config(config):
        sys.exit(1)

    print_banner("Ramp", config, connections=f"{start} → {end} by {step}", interval=f"{interval}s")

    try:
        asyncio.run(_run_ramp(config, start, end, step, interval, output, verbose))
    except KeyboardInterrupt:
        console.print("\n[yellow]Test interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[bold red]Test failed:[/bold red] {e}")
        if verbose:
            console.print_exception()
        sys.exit(1)


async def _run_ramp(config: PipecatConfig, start: int, end: int, step: int, interval: int, output: str, verbose: bool):
    audio_gen = AudioGenerator(config.audio_file) if config.audio_file else AudioGenerator()
    metrics = MetricsCollector()
    orchestrator = LoadOrchestrator(config.host, audio_gen, metrics, config=config)

    total_steps = (end - start) // step + 1

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Ramping up connections...", total=total_steps)

        await orchestrator.run_ramp(
            start, end, step, interval,
            progress_callback=lambda current, total: progress.update(task, completed=current, description=f"[cyan]Step {current}/{total}: {start + (current-1) * step} connections")
        )

    metrics.print_summary()
    metrics.save_report(output)
    console.print(f"\n[green]✓ Results saved to {output}[/green]")


@cli.command()
@click.option('--host', '-h', default=None, help='Server host:port')
@click.option('--connections', '-n', default=100, help='Spike connection count (default: 100)')
@click.option('--duration', '-d', default=60, help='Spike duration in seconds (default: 60)')
@click.option('--audio', '-a', default=None, help='Path to audio file')
@click.option('--output', '-o', default=None, help='Output metrics file')
@click.pass_context
def spike(ctx, host, connections, duration, audio, output):
    """Run spike load test: instantly spawn N connections.

    This test creates all connections simultaneously to test
    how the server handles sudden load spikes.

    Examples:

        # Spike to 100 connections
        pipecat-load-test spike --connections 100

        # Large spike for stress testing
        pipecat-load-test spike -n 500 -d 120
    """
    config = ctx.obj['config']
    verbose = ctx.obj['verbose']

    if host:
        config.host = host
    if audio:
        config.audio_file = audio
    output = output or config.default_output

    if not validate_config(config):
        sys.exit(1)

    print_banner("Spike", config, connections=connections, duration=f"{duration}s")

    try:
        asyncio.run(_run_spike(config, connections, duration, output, verbose))
    except KeyboardInterrupt:
        console.print("\n[yellow]Test interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[bold red]Test failed:[/bold red] {e}")
        if verbose:
            console.print_exception()
        sys.exit(1)


async def _run_spike(config: PipecatConfig, connections: int, duration: int, output: str, verbose: bool):
    audio_gen = AudioGenerator(config.audio_file) if config.audio_file else AudioGenerator()
    metrics = MetricsCollector()
    orchestrator = LoadOrchestrator(config.host, audio_gen, metrics, config=config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[cyan]Spiking {connections} connections...",
            total=duration
        )

        await orchestrator.run_spike(connections, duration, progress_callback=lambda elapsed: progress.update(task, completed=elapsed))

    metrics.print_summary()
    metrics.save_report(output)
    console.print(f"\n[green]✓ Results saved to {output}[/green]")


@cli.command()
@click.pass_context
def show_config(ctx):
    """Show current configuration.

    Displays the merged configuration from defaults,
    config file, and environment variables.
    """
    config = ctx.obj['config']

    from rich.table import Table

    table = Table(title="Current Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Source", style="dim")

    for key, value in config.to_dict().items():
        # Determine source
        env_var = f"PIPECAT_{key.upper()}"
        if os.environ.get(env_var):
            source = "env"
        elif value != getattr(PipecatConfig(), key):
            source = "config"
        else:
            source = "default"

        table.add_row(key, str(value) if value is not None else "-", source)

    console.print(table)


@cli.command()
def init():
    """Create a sample configuration file.

    Creates a pipecat-config.yaml file in the current directory
    with all available options and their defaults.
    """
    sample_config = """# Pipecat Load Tester Configuration
# See https://github.com/forkadarshp/ws-load-test for documentation

# Server settings
server:
  host: localhost:8000
  connect_endpoint: /connect
  rtvi_client_version: "0.4.1"

# Audio settings
audio:
  sample_rate: 16000
  channels: 1
  chunk_duration_ms: 60
  # Uncomment to use a custom audio file instead of synthetic sine wave
  # audio_file: samples/greeting.wav

# Connection settings
connection:
  websocket_max_size: 10485760  # 10MB
  websocket_ping_interval: 20
  websocket_ping_timeout: 20
  pipeline_init_delay: 1.5
  connection_timeout: 30.0

# Retry settings
retry:
  max_retries: 3
  retry_delay: 1.0
  retry_backoff_multiplier: 2.0

# Test defaults
test:
  default_connections: 10
  default_duration: 60
  default_output: results.json

# Logging
logging:
  log_level: INFO

# API server (for Testing API)
api:
  api_host: 0.0.0.0
  api_port: 8080
  session_timeout: 300
  max_sessions: 100
"""

    config_path = Path("pipecat-config.yaml")
    if config_path.exists():
        console.print(f"[yellow]Warning: {config_path} already exists. Overwrite? [y/N][/yellow]", end=" ")
        response = input().strip().lower()
        if response != 'y':
            console.print("[dim]Cancelled[/dim]")
            return

    config_path.write_text(sample_config)
    console.print(f"[green]✓ Created {config_path}[/green]")
    console.print("\n[dim]Edit this file to customize your configuration.[/dim]")


# Import os for show_config
import os


if __name__ == '__main__':
    cli()
