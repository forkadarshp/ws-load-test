"""CLI entry point for load testing."""
import asyncio

import click
from rich.console import Console

from .audio import AudioGenerator
from .metrics import MetricsCollector
from .orchestrator import LoadOrchestrator

console = Console()


@click.group()
def cli():
    """Pipecat Load Testing Tool"""
    pass


@cli.command()
@click.option('--host', default='localhost:8000', help='Server host:port')
@click.option('--connections', '-n', default=10, help='Number of concurrent connections')
@click.option('--duration', '-d', default=60, help='Test duration in seconds')
@click.option('--audio', '-a', default=None, help='Path to audio file (.wav). If not provided, uses synthetic sine wave.')
@click.option('--output', '-o', default='results.json', help='Output metrics file')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def sustained(host, connections, duration, audio, output, verbose):
    """Run sustained load test with N connections for D seconds."""
    console.print(f"[bold cyan]Pipecat Load Test - Sustained[/bold cyan]")
    console.print(f"Host: {host}")
    console.print(f"Connections: {connections}")
    console.print(f"Duration: {duration}s")
    console.print(f"Audio: {audio or 'synthetic sine wave'}")

    asyncio.run(_run_sustained(host, connections, duration, audio, output, verbose))


async def _run_sustained(host, connections, duration, audio, output, verbose):
    audio_gen = AudioGenerator(audio) if audio else AudioGenerator()
    metrics = MetricsCollector()
    orchestrator = LoadOrchestrator(host, audio_gen, metrics)

    await orchestrator.run_sustained(connections, duration)

    metrics.print_summary()
    metrics.save_report(output)
    console.print(f"[green]Results saved to {output}[/green]")


@cli.command()
@click.option('--host', default='localhost:8000')
@click.option('--start', default=10, help='Starting connections')
@click.option('--end', default=100, help='Ending connections')
@click.option('--step', default=10, help='Increment step')
@click.option('--interval', default=30, help='Seconds between steps')
@click.option('--audio', '-a', default=None)
@click.option('--output', '-o', default='results.json')
def ramp(host, start, end, step, interval, audio, output):
    """Run ramp-up load test: gradually increase connections."""
    console.print(f"[bold cyan]Pipecat Load Test - Ramp[/bold cyan]")
    console.print(f"Host: {host}")
    console.print(f"Connections: {start} → {end} by {step}")
    console.print(f"Interval: {interval}s")

    asyncio.run(_run_ramp(host, start, end, step, interval, audio, output))


async def _run_ramp(host, start, end, step, interval, audio, output):
    audio_gen = AudioGenerator(audio) if audio else AudioGenerator()
    metrics = MetricsCollector()
    orchestrator = LoadOrchestrator(host, audio_gen, metrics)

    await orchestrator.run_ramp(start, end, step, interval)

    metrics.print_summary()
    metrics.save_report(output)
    console.print(f"[green]Results saved to {output}[/green]")


@cli.command()
@click.option('--host', default='localhost:8000')
@click.option('--connections', default=100, help='Spike connection count')
@click.option('--duration', default=60, help='Spike duration in seconds')
@click.option('--audio', '-a', default=None)
@click.option('--output', '-o', default='results.json')
def spike(host, connections, duration, audio, output):
    """Run spike load test: instantly spawn N connections."""
    console.print(f"[bold cyan]Pipecat Load Test - Spike[/bold cyan]")
    console.print(f"Host: {host}")
    console.print(f"Connections: {connections}")
    console.print(f"Duration: {duration}s")

    asyncio.run(_run_spike(host, connections, duration, audio, output))


async def _run_spike(host, connections, duration, audio, output):
    audio_gen = AudioGenerator(audio) if audio else AudioGenerator()
    metrics = MetricsCollector()
    orchestrator = LoadOrchestrator(host, audio_gen, metrics)

    await orchestrator.run_spike(connections, duration)

    metrics.print_summary()
    metrics.save_report(output)
    console.print(f"[green]Results saved to {output}[/green]")


if __name__ == '__main__':
    cli()
