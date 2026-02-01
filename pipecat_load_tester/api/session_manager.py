"""Session management for Testing API."""
import asyncio
import uuid
from typing import Dict, Optional, List
from datetime import datetime

from .websocket_client import WebSocketSession


class SessionManager:
    """Manages active WebSocket sessions."""

    def __init__(self):
        self.sessions: Dict[str, WebSocketSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(self, bot_host: str) -> str:
        """Creates a new session and connects to bot."""
        session_id = str(uuid.uuid4())

        async with self._lock:
            session = WebSocketSession(bot_host)
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

    async def cleanup_inactive(self, timeout_seconds: int = 3600):
        """Removes sessions inactive for > timeout."""
        now = datetime.now()
        to_remove = []

        async with self._lock:
            for sid, session in self.sessions.items():
                age = (now - session.last_activity).total_seconds()
                if age > timeout_seconds:
                    to_remove.append(sid)

            for sid in to_remove:
                session = self.sessions.pop(sid, None)
                if session:
                    await session.disconnect()
