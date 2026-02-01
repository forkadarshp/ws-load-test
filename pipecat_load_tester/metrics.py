"""Performance metrics collection and reporting."""
import time
import json
import statistics
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional


@dataclass
class ConnectionMetrics:
    """Metrics for a single connection."""
    connection_id: int
    connect_time: Optional[float] = None
    frames_sent: int = 0
    bytes_sent: int = 0
    frames_received: int = 0
    errors: List[dict] = field(default_factory=list)


class MetricsCollector:
    """Aggregates metrics across all connections."""

    def __init__(self):
        self.start_time = time.time()
        self.connections: Dict[int, ConnectionMetrics] = {}
        self.events: List[dict] = []

        self.total_connections_attempted = 0
        self.total_connections_successful = 0
        self.total_frames_sent = 0
        self.total_bytes_sent = 0
        self.total_frames_received = 0
        self.total_errors = 0

    async def record_event(self, event: dict):
        """Records an event from a connection."""
        event['timestamp'] = time.time() - self.start_time
        self.events.append(event)

        conn_id = event.get('connection_id')

        if event['event'] == 'connected':
            self.total_connections_successful += 1
            if conn_id not in self.connections:
                self.connections[conn_id] = ConnectionMetrics(connection_id=conn_id)
            self.connections[conn_id].connect_time = event.get('connect_time')

        elif event['event'] == 'error':
            self.total_errors += 1

    def update_from_connection(self, conn: 'PipecatConnection'):
        """Updates metrics from a connection object."""
        metrics = conn.get_metrics()
        conn_id = metrics['connection_id']

        if conn_id not in self.connections:
            self.connections[conn_id] = ConnectionMetrics(connection_id=conn_id)

        self.connections[conn_id].frames_sent = metrics['frames_sent']
        self.connections[conn_id].bytes_sent = metrics['bytes_sent']
        self.connections[conn_id].frames_received = metrics['frames_received']
        self.connections[conn_id].errors = metrics['errors']

        self.total_frames_sent += metrics['frames_sent']
        self.total_bytes_sent += metrics['bytes_sent']
        self.total_frames_received += metrics['frames_received']
        self.total_errors += len(metrics['errors'])

    def generate_report(self) -> dict:
        """Generates comprehensive test report."""
        duration = time.time() - self.start_time

        success_rate = (
            self.total_connections_successful / self.total_connections_attempted
            if self.total_connections_attempted > 0 else 0
        )

        connect_times = [
            c.connect_time for c in self.connections.values()
            if c.connect_time is not None
        ]

        frames_sent_per_conn = [c.frames_sent for c in self.connections.values()]

        report = {
            'summary': {
                'duration_seconds': round(duration, 2),
                'total_connections_attempted': self.total_connections_attempted,
                'total_connections_successful': self.total_connections_successful,
                'success_rate': round(success_rate * 100, 2),
                'total_frames_sent': self.total_frames_sent,
                'total_bytes_sent': self.total_bytes_sent,
                'total_frames_received': self.total_frames_received,
                'total_errors': self.total_errors,
            },
            'performance': {
                'avg_connect_time_ms': round(statistics.mean(connect_times) * 1000, 2) if connect_times else 0,
                'min_connect_time_ms': round(min(connect_times) * 1000, 2) if connect_times else 0,
                'max_connect_time_ms': round(max(connect_times) * 1000, 2) if connect_times else 0,
                'avg_frames_per_connection': round(statistics.mean(frames_sent_per_conn), 2) if frames_sent_per_conn else 0,
                'throughput_frames_per_sec': round(self.total_frames_sent / duration, 2) if duration > 0 else 0,
                'throughput_mbps': round((self.total_bytes_sent * 8 / 1_000_000) / duration, 2) if duration > 0 else 0,
            },
            'connections': [asdict(c) for c in self.connections.values()],
        }

        return report

    def save_report(self, filename: str):
        """Saves report to JSON file."""
        report = self.generate_report()
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)

    def print_summary(self):
        """Prints human-readable summary to console."""
        from rich.console import Console
        from rich.table import Table

        console = Console()
        report = self.generate_report()

        table = Table(title="Load Test Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        for key, value in report['summary'].items():
            table.add_row(key.replace('_', ' ').title(), str(value))

        console.print(table)

        perf_table = Table(title="Performance Metrics")
        perf_table.add_column("Metric", style="cyan")
        perf_table.add_column("Value", style="yellow")

        for key, value in report['performance'].items():
            perf_table.add_row(key.replace('_', ' ').title(), str(value))

        console.print(perf_table)
