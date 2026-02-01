"""Load pattern orchestration for load testing."""
import asyncio
import logging
import time
from typing import List, Optional, Callable

from .connection import PipecatConnection
from .audio import AudioGenerator
from .metrics import MetricsCollector
from .config import PipecatConfig

logger = logging.getLogger(__name__)


class LoadOrchestrator:
    """Manages load testing patterns."""

    def __init__(
        self,
        host: str,
        audio_generator: AudioGenerator,
        metrics_collector: MetricsCollector,
        config: Optional[PipecatConfig] = None
    ):
        self.host = host
        self.audio_generator = audio_generator
        self.metrics = metrics_collector
        self.config = config or PipecatConfig()
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
            metrics_callback=self.metrics.record_event,
            config=self.config
        )

        self.metrics.total_connections_attempted += 1

        try:
            # Attempt connection with retries
            success = await self._connect_with_retry(conn)
            if not success:
                return conn

            await conn.stream_audio(duration=duration)
        except asyncio.CancelledError:
            logger.debug(f"Connection {connection_id} cancelled")
            raise
        finally:
            # Always disconnect and update metrics
            await conn.disconnect()
            self.metrics.update_from_connection(conn)

        return conn

    async def _connect_with_retry(self, conn: PipecatConnection) -> bool:
        """Attempt connection with retry logic."""
        max_retries = self.config.max_retries
        delay = self.config.retry_delay
        backoff = self.config.retry_backoff_multiplier

        for attempt in range(max_retries + 1):
            success = await conn.connect()
            if success:
                return True

            if attempt < max_retries:
                logger.debug(f"Connection {conn.connection_id} failed (attempt {attempt + 1}/{max_retries + 1}), retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
                delay *= backoff

        logger.warning(f"Connection {conn.connection_id} failed after {max_retries + 1} attempts")
        return False

    async def run_sustained(
        self,
        num_connections: int,
        duration: float,
        progress_callback: Optional[Callable[[float], None]] = None
    ):
        """
        Runs sustained load test: N connections for X seconds.

        Args:
            num_connections: Number of concurrent connections.
            duration: Test duration in seconds.
            progress_callback: Optional callback with elapsed seconds.
        """
        logger.info(f"Starting sustained load: {num_connections} connections for {duration}s")

        start_time = time.time()

        # Create tasks for all connections
        tasks = [
            asyncio.create_task(self.spawn_connection(i, duration=duration))
            for i in range(num_connections)
        ]

        # If we have a progress callback, run progress updates while waiting
        if progress_callback:
            while tasks:
                # Wait for next completion or timeout
                done, pending = await asyncio.wait(
                    tasks,
                    timeout=0.5,
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Update progress
                elapsed = min(time.time() - start_time, duration)
                progress_callback(elapsed)

                # Collect completed connections
                for task in done:
                    try:
                        conn = task.result()
                        if isinstance(conn, PipecatConnection):
                            self.connections.append(conn)
                    except Exception as e:
                        logger.error(f"Connection task error: {e}")

                # Update remaining tasks
                tasks = list(pending)

                # Check if duration exceeded
                if time.time() - start_time >= duration:
                    break

            # Cancel remaining tasks and collect their connections
            for task in tasks:
                if not task.done():
                    task.cancel()

            # Wait for all cancelled tasks to complete cleanup
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for conn in results:
                    if isinstance(conn, PipecatConnection):
                        self.connections.append(conn)
        else:
            # Simple gather without progress
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for conn in results:
                if isinstance(conn, PipecatConnection):
                    self.connections.append(conn)

        logger.info(f"Test complete. {len(self.connections)} connections finished.")

    async def run_ramp(
        self,
        start_connections: int,
        end_connections: int,
        step: int,
        interval: float,
        audio_duration: Optional[float] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ):
        """
        Runs ramp-up test: Gradually increase connections.

        Args:
            start_connections: Starting number of connections.
            end_connections: Final number of connections.
            step: Increment per interval.
            interval: Seconds between increments.
            audio_duration: Duration for each connection to stream.
            progress_callback: Optional callback with (current_step, total_steps).
        """
        logger.info(f"Starting ramp test: {start_connections} → {end_connections} by {step} every {interval}s")

        current = start_connections
        connection_id = 0
        all_tasks = []

        total_steps = (end_connections - start_connections) // step + 1
        current_step = 0

        while current <= end_connections:
            current_step += 1
            logger.info(f"Step {current_step}/{total_steps}: Spawning {current} connections...")

            if progress_callback:
                progress_callback(current_step, total_steps)

            # Create tasks for this batch
            batch_tasks = [
                asyncio.create_task(self.spawn_connection(connection_id + i, duration=audio_duration or interval))
                for i in range(current)
            ]
            all_tasks.extend(batch_tasks)
            connection_id += current

            await asyncio.sleep(interval)
            current += step

        logger.info("Waiting for all connections to complete...")

        # Wait for all remaining tasks
        if all_tasks:
            results = await asyncio.gather(*all_tasks, return_exceptions=True)
            for conn in results:
                if isinstance(conn, PipecatConnection):
                    self.connections.append(conn)

    async def run_spike(
        self,
        num_connections: int,
        duration: float,
        progress_callback: Optional[Callable[[float], None]] = None
    ):
        """
        Runs spike test: Instantly spawn N connections.

        Args:
            num_connections: Number of connections to spike.
            duration: How long to maintain spike.
            progress_callback: Optional callback with elapsed seconds.
        """
        logger.info(f"Starting spike test: {num_connections} connections instantly")
        await self.run_sustained(num_connections, duration, progress_callback)
