"""Load pattern orchestration for load testing."""
import asyncio
from typing import List, Optional

from .connection import PipecatConnection
from .audio import AudioGenerator
from .metrics import MetricsCollector


class LoadOrchestrator:
    """Manages load testing patterns."""

    def __init__(
        self,
        host: str,
        audio_generator: AudioGenerator,
        metrics_collector: MetricsCollector
    ):
        self.host = host
        self.audio_generator = audio_generator
        self.metrics = metrics_collector
        self.connections: List[PipecatConnection] = []

    async def spawn_connection(
        self,
        connection_id: int,
        duration: Optional[float] = None
    ) -> PipecatConnection:
        """
        Spawns a single connection and starts streaming.

        Args:
            connection_id: Unique ID for this connection.
            duration: How long to stream audio (None = until audio ends).

        Returns:
            PipecatConnection instance.
        """
        conn = PipecatConnection(
            host=self.host,
            connection_id=connection_id,
            audio_generator=self.audio_generator,
            metrics_callback=self.metrics.record_event
        )

        self.metrics.total_connections_attempted += 1

        success = await conn.connect()
        if not success:
            return conn

        await conn.stream_audio(duration=duration)
        await conn.disconnect()
        self.metrics.update_from_connection(conn)

        return conn

    async def run_sustained(self, num_connections: int, duration: float):
        """
        Runs sustained load test: N connections for X seconds.

        Args:
            num_connections: Number of concurrent connections.
            duration: Test duration in seconds.
        """
        print(f"Starting sustained load: {num_connections} connections for {duration}s")

        tasks = [
            self.spawn_connection(i, duration=duration)
            for i in range(num_connections)
        ]

        connections = await asyncio.gather(*tasks, return_exceptions=True)
        
        for conn in connections:
            if isinstance(conn, PipecatConnection):
                self.connections.append(conn)

        print(f"Test complete. {len(self.connections)} connections finished.")

    async def run_ramp(
        self,
        start_connections: int,
        end_connections: int,
        step: int,
        interval: float,
        audio_duration: Optional[float] = None
    ):
        """
        Runs ramp-up test: Gradually increase connections.

        Args:
            start_connections: Starting number of connections.
            end_connections: Final number of connections.
            step: Increment per interval.
            interval: Seconds between increments.
            audio_duration: Duration for each connection to stream.
        """
        print(f"Starting ramp test: {start_connections} → {end_connections} by {step} every {interval}s")

        current = start_connections
        connection_id = 0
        batch_tasks = []

        async def run_batch(batch_tasks_list):
            """Run a batch of connections."""
            return await asyncio.gather(*batch_tasks_list, return_exceptions=True)

        while current <= end_connections:
            print(f"Spawning {current} connections...")

            tasks = [
                self.spawn_connection(connection_id + i, duration=audio_duration or interval)
                for i in range(current)
            ]
            connection_id += current

            # Create a task for this batch that runs in background
            batch_task = asyncio.create_task(run_batch(tasks))
            batch_tasks.append(batch_task)

            await asyncio.sleep(interval)
            current += step

        print("Waiting for all connections to complete...")
        await asyncio.gather(*batch_tasks, return_exceptions=True)

    async def run_spike(self, num_connections: int, duration: float):
        """
        Runs spike test: Instantly spawn N connections.

        Args:
            num_connections: Number of connections to spike.
            duration: How long to maintain spike.
        """
        print(f"Starting spike test: {num_connections} connections instantly")
        await self.run_sustained(num_connections, duration)
