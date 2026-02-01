"""WebSocket connection management with RTVI handshake."""
import asyncio
import json
import time
from typing import Optional, Callable
from uuid import uuid4

import aiohttp
import websockets

from .frames_pb2 import Frame


class PipecatConnection:
    """Manages a single WebSocket connection to Pipecat bot with RTVI handshake."""

    def __init__(
        self,
        host: str,
        connection_id: int,
        audio_generator: 'AudioGenerator',
        metrics_callback: Optional[Callable] = None
    ):
        self.host = host
        self.connection_id = connection_id
        self.audio_generator = audio_generator
        self.metrics_callback = metrics_callback

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

            # Step 1: POST /connect
            self.http_session = aiohttp.ClientSession()
            async with self.http_session.post(
                f"http://{self.host}/connect",
                json={"rtvi_client_version": "0.4.1"}
            ) as response:
                if response.status != 200:
                    raise Exception(f"Connect failed: {response.status}")
                data = await response.json()
                ws_url = data.get("ws_url")
                if not ws_url:
                    raise Exception("No ws_url in response")

            # Step 2: WebSocket connect
            self.websocket = await websockets.connect(
                ws_url,
                max_size=10 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=20
            )
            self.is_connected = True

            # Step 3: Wait for pipeline to initialize before sending client-ready
            await asyncio.sleep(1.5)

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
                                break
                            elif data.get("type") == "error":
                                raise Exception(f"Bot error: {data.get('data', {}).get('message', 'unknown')}")
                        except json.JSONDecodeError:
                            pass

            self.connect_time = time.time() - start_time

            if self.metrics_callback:
                await self.metrics_callback({
                    'event': 'connected',
                    'connection_id': self.connection_id,
                    'connect_time': self.connect_time
                })

            return True

        except Exception as e:
            self.errors.append({'time': time.time(), 'error': str(e), 'phase': 'connect'})
            if self.metrics_callback:
                await self.metrics_callback({
                    'event': 'error',
                    'connection_id': self.connection_id,
                    'error': str(e)
                })
            return False

    async def send_audio_frame(self, audio_data: bytes) -> bool:
        """Sends a single audio frame to the bot."""
        if not self.is_connected or not self.websocket or not self.bot_ready:
            return False

        try:
            frame = Frame()
            frame.audio.id = self.frame_id
            frame.audio.name = "audio"
            frame.audio.audio = audio_data
            frame.audio.sample_rate = 16000
            frame.audio.num_channels = 1

            frame_bytes = frame.SerializeToString()
            await self.websocket.send(frame_bytes)

            self.frame_id += 1
            self.frames_sent += 1
            self.bytes_sent += len(frame_bytes)
            return True

        except Exception as e:
            self.errors.append({'time': time.time(), 'error': str(e), 'phase': 'send_audio'})
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
            self.errors.append({'time': time.time(), 'error': str(e), 'phase': 'send_text'})
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

        except websockets.exceptions.ConnectionClosed:
            self.is_connected = False
        except Exception as e:
            self.errors.append({'time': time.time(), 'error': str(e), 'phase': 'receive'})

    async def stream_audio(self, duration: Optional[float] = None):
        """Streams audio chunks to the bot."""
        start_time = time.time()
        receive_task = asyncio.create_task(self.receive_loop())

        try:
            for chunk in self.audio_generator.generate_chunks(loop=duration is not None):
                if duration and (time.time() - start_time) >= duration:
                    break

                if not await self.send_audio_frame(chunk):
                    break

                await asyncio.sleep(0.06)  # 60ms per chunk

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
                await asyncio.wait_for(self.websocket.close(), timeout=1.0)
            except Exception:
                pass
            self.websocket = None

        if self.http_session:
            try:
                await asyncio.wait_for(self.http_session.close(), timeout=1.0)
            except Exception:
                pass
            self.http_session = None

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
