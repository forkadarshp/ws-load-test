"""Session management for Testing API."""
import asyncio
import uuid
from typing import Dict, Optional, List
from datetime import datetime

from .websocket_client import WebSocketSession
from ..config import PipecatConfig


class SessionManager:
    """Manages active WebSocket sessions."""

    def __init__(self, config: Optional[PipecatConfig] = None):
        self.config = config or PipecatConfig()
        self.sessions: Dict[str, WebSocketSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(self, bot_host: str) -> str:
        """Creates a new session and connects to bot."""
        # Check max sessions limit
        if len(self.sessions) >= self.config.max_sessions:
            raise Exception(f"Maximum sessions ({self.config.max_sessions}) reached")

        session_id = str(uuid.uuid4())

        async with self._lock:
            session = WebSocketSession(bot_host, config=self.config)
            session.session_id = session_id
            await session.connect()
            self.sessions[session_id] = session

        return session_id

    def get_session(self, session_id: str) -> Optional[WebSocketSession]:
        """Retrieves a session by ID."""
        return self.sessions.get(session_id)

    async def close_session(self, session_id: str) -> dict:
        """Closes and removes a session."""
        async with self._lock:
            session = self.sessions.pop(session_id, None)

            if session:
                metrics = session.get_metrics()
                await session.disconnect()
                return metrics

            return {}

    async def close_all(self):
        """Close all active sessions."""
        async with self._lock:
            for session_id, session in list(self.sessions.items()):
                try:
                    await session.disconnect()
                except Exception:
                    pass
            self.sessions.clear()

    def list_sessions(self) -> List[dict]:
        """Lists all active sessions."""
        return [
            {
                "session_id": sid,
                "status": session.status,
                "created_at": session.created_at,
                "uptime_seconds": (datetime.now() - session.created_at).total_seconds()
            }
            for sid, session in self.sessions.items()
        ]

    async def cleanup_inactive(self, timeout_seconds: Optional[int] = None):
        """Removes sessions inactive for > timeout."""
        timeout = timeout_seconds or self.config.session_timeout
        now = datetime.now()
        to_remove = []

        async with self._lock:
            for sid, session in self.sessions.items():
                age = (now - session.last_activity).total_seconds()
                if age > timeout:
                    to_remove.append(sid)

            for sid in to_remove:
                session = self.sessions.pop(sid, None)
                if session:
                    await session.disconnect()
