"""Pydantic models for Testing API."""
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime


class StartSessionRequest(BaseModel):
    bot_host: str = Field(default="localhost:8000", description="Bot server host:port")


class StartSessionResponse(BaseModel):
    session_id: str
    status: str
    ws_url: str
    created_at: datetime


class SendTextRequest(BaseModel):
    text: str = Field(..., description="Text to send to bot")


class SendTextResponse(BaseModel):
    sent: bool
    frame_id: int


class AudioSendResponse(BaseModel):
    frames_sent: int
    duration_ms: int
    bytes_sent: int


class MessageData(BaseModel):
    type: Optional[str] = None
    timestamp: float
    data: dict = Field(default_factory=dict)


class MessagesResponse(BaseModel):
    session_id: str
    messages: List[MessageData]
    total_messages: int


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    uptime_seconds: float
    frames_sent: int
    frames_received: int
    bytes_sent: int
    last_activity: datetime


class SessionInfo(BaseModel):
    session_id: str
    status: str
    created_at: datetime
    uptime_seconds: float


class SessionListResponse(BaseModel):
    sessions: List[SessionInfo]
    total_active: int


class CloseSessionResponse(BaseModel):
    session_id: str
    status: str
    final_metrics: dict
