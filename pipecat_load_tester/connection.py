"""WebSocket connection management with RTVI handshake."""
import asyncio
import json
import logging
import time
from typing import Optional, Callable
from uuid import uuid4

import aiohttp
import websockets
from websockets import ConnectionClosed, WebSocketException

from .frames_pb2 import Frame
from .config import PipecatConfig

logger = logging.getLogger(__name__)


class PipecatConnection:
    """Manages a single WebSocket connection to Pipecat bot with RTVI handshake."""

    def __init__(
        self,
        host: str,
        connection_id: int,
        audio_generator: 'AudioGenerator',
        metrics_callback: Optional[Callable] = None,
        config: Optional[PipecatConfig] = None
    ):
        self.host = host
        self.connection_id = connection_id
        self.audio_generator = audio_generator
        self.metrics_callback = metrics_callback
        self.config = config or PipecatConfig()

        self.http_session: Optional[aiohttp.ClientSession] = None
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.frame_id = 0
        self.is_connected = False
        self.bot_ready = False

        # Metrics
        self.connect_time: Optional[float] = None
        self.frames_sent = 0
        self.bytes_sent = 0
        self.frames_received = 0
        self.errors = []

    async def connect(self) -> bool:
        """
        Establishes connection with RTVI handshake.

        Returns:
            bool: True if connection and handshake successful.
        """
        try:
            start_time = time.time()
            connect_url = f"http://{self.host}{self.config.connect_endpoint}"

            logger.debug(f"Connection {self.connection_id}: POST {connect_url}")

            # Step 1: POST /connect
            timeout = aiohttp.ClientTimeout(total=self.config.connection_timeout)
            self.http_session = aiohttp.ClientSession(timeout=timeout)

            async with self.http_session.post(
                connect_url,
                json={"rtvi_client_version": self.config.rtvi_client_version}
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise ConnectionError(f"Connect failed with status {response.status}: {error_text}")
                data = await response.json()
                ws_url = data.get("ws_url")
                if not ws_url:
                    raise ConnectionError("No ws_url in server response")

            logger.debug(f"Connection {self.connection_id}: WebSocket connecting to {ws_url}")

            # Step 2: WebSocket connect
            self.websocket = await websockets.connect(
                ws_url,
                max_size=self.config.websocket_max_size,
                ping_interval=self.config.websocket_ping_interval,
                ping_timeout=self.config.websocket_ping_timeout
            )
            self.is_connected = True

            # Step 3: Wait for pipeline to initialize before sending client-ready
            await asyncio.sleep(self.config.pipeline_init_delay)

            # Step 4: Send client-ready wrapped in MessageFrame (RTVI protocol)
            client_ready = {
                "label": "rtvi-ai",
                "type": "client-ready",
                "id": str(uuid4())[:8],
                "data": {}
            }
            frame = Frame()
            frame.message.data = json.dumps(client_ready)
            await self.websocket.send(frame.SerializeToString())
            self.frame_id += 1

            logger.debug(f"Connection {self.connection_id}: Waiting for bot-ready...")

            # Step 5: Wait for bot-ready (comes as protobuf MessageFrame)
            async for msg in self.websocket:
                if isinstance(msg, bytes):
                    resp_frame = Frame()
                    resp_frame.ParseFromString(msg)
                    if resp_frame.HasField('message'):
                        try:
                            data = json.loads(resp_frame.message.data)
                            if data.get("type") == "bot-ready":
                                self.bot_ready = True
                                logger.debug(f"Connection {self.connection_id}: Bot ready")
                                break
                            elif data.get("type") == "error":
                                error_msg = data.get('data', {}).get('message', 'unknown')
                                raise ConnectionError(f"Bot error: {error_msg}")
                        except json.JSONDecodeError:
                            pass

            self.connect_time = time.time() - start_time
            logger.debug(f"Connection {self.connection_id}: Connected in {self.connect_time:.2f}s")

            if self.metrics_callback:
                await self.metrics_callback({
                    'event': 'connected',
                    'connection_id': self.connection_id,
                    'connect_time': self.connect_time
                })

            return True

        except asyncio.TimeoutError:
            error_msg = "Connection timed out"
            self._record_error(error_msg, 'connect')
            return False
        except aiohttp.ClientError as e:
            error_msg = f"HTTP error: {e}"
            self._record_error(error_msg, 'connect')
            return False
        except WebSocketException as e:
            error_msg = f"WebSocket error: {e}"
            self._record_error(error_msg, 'connect')
            return False
        except Exception as e:
            error_msg = str(e)
            self._record_error(error_msg, 'connect')
            return False

    def _record_error(self, error: str, phase: str):
        """Record an error and notify via callback."""
        logger.warning(f"Connection {self.connection_id}: {phase} error - {error}")
        self.errors.append({'time': time.time(), 'error': error, 'phase': phase})
        if self.metrics_callback:
            asyncio.create_task(self.metrics_callback({
                'event': 'error',
                'connection_id': self.connection_id,
                'error': error
            }))

    async def send_audio_frame(self, audio_data: bytes) -> bool:
        """Sends a single audio frame to the bot."""
        if not self.is_connected or not self.websocket or not self.bot_ready:
            return False

        try:
            frame = Frame()
            frame.audio.id = self.frame_id
            frame.audio.name = "audio"
            frame.audio.audio = audio_data
            frame.audio.sample_rate = self.config.sample_rate
            frame.audio.num_channels = self.config.channels

            frame_bytes = frame.SerializeToString()
            await self.websocket.send(frame_bytes)

            self.frame_id += 1
            self.frames_sent += 1
            self.bytes_sent += len(frame_bytes)
            return True

        except Exception as e:
            self._record_error(str(e), 'send_audio')
            return False

    async def send_text_frame(self, text: str) -> bool:
        """Sends text to the bot via RTVI send-text message."""
        if not self.is_connected or not self.websocket or not self.bot_ready:
            return False

        try:
            # RTVI send-text message format
            send_text_msg = {
                "label": "rtvi-ai",
                "type": "send-text",
                "id": str(uuid4())[:8],
                "data": {
                    "content": text
                }
            }

            frame = Frame()
            frame.message.data = json.dumps(send_text_msg)
            frame_bytes = frame.SerializeToString()
            await self.websocket.send(frame_bytes)

            self.frame_id += 1
            self.frames_sent += 1
            self.bytes_sent += len(frame_bytes)
            return True

        except Exception as e:
            self._record_error(str(e), 'send_text')
            return False

    async def receive_loop(self):
        """Background task to receive messages from server."""
        if not self.websocket:
            return

        try:
            async for message in self.websocket:
                if isinstance(message, bytes):
                    frame = Frame()
                    frame.ParseFromString(message)
                    self.frames_received += 1

                    if self.metrics_callback:
                        if frame.HasField('transcription'):
                            await self.metrics_callback({
                                'event': 'transcription',
                                'connection_id': self.connection_id,
                                'text': frame.transcription.text
                            })
                        elif frame.HasField('audio'):
                            await self.metrics_callback({
                                'event': 'bot_audio',
                                'connection_id': self.connection_id,
                                'size': len(frame.audio.audio)
                            })
                        elif frame.HasField('message'):
                            try:
                                data = json.loads(frame.message.data)
                                await self.metrics_callback({
                                    'event': 'rtvi_message',
                                    'connection_id': self.connection_id,
                                    'type': data.get('type')
                                })
                            except json.JSONDecodeError:
                                pass

        except ConnectionClosed:
            self.is_connected = False
            logger.debug(f"Connection {self.connection_id}: WebSocket closed")
        except Exception as e:
            self._record_error(str(e), 'receive')

    async def stream_audio(self, duration: Optional[float] = None):
        """Streams audio chunks to the bot."""
        start_time = time.time()
        receive_task = asyncio.create_task(self.receive_loop())

        chunk_interval = self.config.chunk_duration_ms / 1000.0

        try:
            for chunk in self.audio_generator.generate_chunks(loop=duration is not None):
                if duration and (time.time() - start_time) >= duration:
                    break

                if not await self.send_audio_frame(chunk):
                    break

                await asyncio.sleep(chunk_interval)

        finally:
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass

    async def disconnect(self):
        """Gracefully closes the connection."""
        self.is_connected = False
        self.bot_ready = False

        if self.websocket:
            try:
                await asyncio.wait_for(
                    self.websocket.close(),
                    timeout=self.config.disconnect_timeout
                )
            except Exception:
                pass
            self.websocket = None

        if self.http_session:
            try:
                await asyncio.wait_for(
                    self.http_session.close(),
                    timeout=self.config.disconnect_timeout
                )
            except Exception:
                pass
            self.http_session = None

        logger.debug(f"Connection {self.connection_id}: Disconnected")

    def get_metrics(self) -> dict:
        """Returns metrics for this connection."""
        return {
            'connection_id': self.connection_id,
            'connect_time': self.connect_time,
            'frames_sent': self.frames_sent,
            'bytes_sent': self.bytes_sent,
            'frames_received': self.frames_received,
            'errors': self.errors
        }
