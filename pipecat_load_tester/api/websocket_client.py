"""WebSocket session wrapper for Testing API."""
import asyncio
import json
import time
from typing import Optional, List
from datetime import datetime
from uuid import uuid4

import aiohttp
import websockets
from websockets import ConnectionClosed

from ..frames_pb2 import Frame
from ..audio import AudioGenerator
from ..config import PipecatConfig


class WebSocketSession:
    """Represents a single WebSocket session to Pipecat bot."""

    def __init__(self, bot_host: str, config: Optional[PipecatConfig] = None):
        self.bot_host = bot_host
        self.config = config or PipecatConfig()
        self.session_id: Optional[str] = None
        self.ws_url: Optional[str] = None
        self.created_at = datetime.now()
        self.last_activity = datetime.now()

        self.http_session: Optional[aiohttp.ClientSession] = None
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None

        self.status = "initializing"
        self.frame_id = 0

        # Metrics
        self.frames_sent = 0
        self.bytes_sent = 0
        self.frames_received = 0
        self.messages: List[dict] = []

        self._receive_task: Optional[asyncio.Task] = None

    async def connect(self):
        """Connects to Pipecat bot with RTVI handshake."""
        try:
            # Step 1: POST /connect
            timeout = aiohttp.ClientTimeout(total=self.config.connection_timeout)
            self.http_session = aiohttp.ClientSession(timeout=timeout)

            async with self.http_session.post(
                f"http://{self.bot_host}{self.config.connect_endpoint}",
                json={"rtvi_client_version": self.config.rtvi_client_version}
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Connect failed: {response.status} - {error_text}")
                data = await response.json()
                self.ws_url = data.get("ws_url")

            # Step 2: WebSocket connect
            self.websocket = await websockets.connect(
                self.ws_url,
                max_size=self.config.websocket_max_size,
                ping_interval=self.config.websocket_ping_interval,
                ping_timeout=self.config.websocket_ping_timeout
            )

            # Step 3: Wait for pipeline to initialize
            await asyncio.sleep(self.config.pipeline_init_delay)

            # Step 4: Send client-ready wrapped in MessageFrame (RTVI protocol)
            client_ready = {
                "label": "rtvi-ai",
                "type": "client-ready",
                "id": str(uuid4())[:8],
                "data": {
                    "version": self.config.rtvi_client_version,
                    "about": {
                        "library": "pipecat-testing-api",
                        "library_version": "1.0.0",
                        "platform": "python"
                    }
                }
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
                                break
                            elif data.get("type") == "error":
                                raise Exception(f"Bot error: {data.get('data', {}).get('message', 'unknown')}")
                        except json.JSONDecodeError:
                            pass

            # Start receive loop
            self._receive_task = asyncio.create_task(self._receive_loop())
            self.status = "connected"
            self.last_activity = datetime.now()

        except Exception as e:
            self.status = "error"
            raise Exception(f"Connection failed: {str(e)}")

    async def _receive_loop(self):
        """Background task to receive messages."""
        try:
            async for message in self.websocket:
                self.frames_received += 1
                self.last_activity = datetime.now()

                msg_data = {"timestamp": time.time(), "type": None, "data": {}}

                if isinstance(message, bytes):
                    frame = Frame()
                    frame.ParseFromString(message)

                    if frame.HasField('transcription'):
                        msg_data["type"] = "transcription"
                        msg_data["data"] = {
                            "text": frame.transcription.text,
                            "user_id": frame.transcription.user_id,
                            "timestamp": frame.transcription.timestamp
                        }
                    elif frame.HasField('audio'):
                        msg_data["type"] = "audio"
                        msg_data["data"] = {
                            "size_bytes": len(frame.audio.audio),
                            "sample_rate": frame.audio.sample_rate
                        }
                    elif frame.HasField('message'):
                        try:
                            rtvi_data = json.loads(frame.message.data)
                            msg_data["type"] = "rtvi"
                            msg_data["data"] = rtvi_data
                        except json.JSONDecodeError:
                            msg_data["type"] = "message"
                            msg_data["data"] = {"raw": frame.message.data}
                    elif frame.HasField('text'):
                        msg_data["type"] = "text"
                        msg_data["data"] = {"text": frame.text.text}

                elif isinstance(message, str):
                    msg_data["type"] = "json"
                    msg_data["data"] = json.loads(message)

                self.messages.append(msg_data)

                # Keep buffer bounded
                if len(self.messages) > 1000:
                    self.messages = self.messages[-1000:]

        except ConnectionClosed:
            self.status = "disconnected"
        except Exception:
            self.status = "error"

    async def send_audio_file(self, audio_data: bytes) -> dict:
        """Sends audio file to bot."""
        if self.status != "connected":
            raise Exception("Not connected")

        audio_gen = AudioGenerator.from_bytes(audio_data)

        frames_sent = 0
        total_bytes = 0
        chunk_interval = self.config.chunk_duration_ms / 1000.0

        for chunk in audio_gen.generate_chunks():
            frame = Frame()
            frame.audio.id = self.frame_id
            frame.audio.name = "audio"
            frame.audio.audio = chunk
            frame.audio.sample_rate = self.config.sample_rate
            frame.audio.num_channels = self.config.channels

            frame_bytes = frame.SerializeToString()
            await self.websocket.send(frame_bytes)

            self.frame_id += 1
            frames_sent += 1
            total_bytes += len(frame_bytes)

            await asyncio.sleep(chunk_interval)

        self.frames_sent += frames_sent
        self.bytes_sent += total_bytes
        self.last_activity = datetime.now()

        return {
            "frames_sent": frames_sent,
            "duration_ms": frames_sent * self.config.chunk_duration_ms,
            "bytes_sent": total_bytes
        }

    async def send_text(self, text: str) -> int:
        """Sends text to bot via RTVI send-text message."""
        if self.status != "connected":
            raise Exception("Not connected")

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
        self.last_activity = datetime.now()

        return self.frame_id - 1

    def get_messages(self, limit: int = 100, since: Optional[float] = None) -> List[dict]:
        """Retrieves messages from bot."""
        messages = self.messages
        if since:
            messages = [m for m in messages if m["timestamp"] > since]
        return messages[-limit:]

    def get_status(self) -> dict:
        """Returns current status."""
        uptime = (datetime.now() - self.created_at).total_seconds()
        return {
            "session_id": self.session_id or "unknown",
            "status": self.status,
            "uptime_seconds": round(uptime, 2),
            "frames_sent": self.frames_sent,
            "frames_received": self.frames_received,
            "bytes_sent": self.bytes_sent,
            "last_activity": self.last_activity
        }

    def get_metrics(self) -> dict:
        """Returns final metrics."""
        return {
            "total_frames_sent": self.frames_sent,
            "total_frames_received": self.frames_received,
            "duration_seconds": (datetime.now() - self.created_at).total_seconds()
        }

    async def disconnect(self):
        """Closes connection."""
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

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

        self.status = "closed"
