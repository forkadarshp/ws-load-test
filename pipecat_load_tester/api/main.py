"""FastAPI Testing API for Pipecat voice bot."""
import os
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    StartSessionRequest,
    StartSessionResponse,
    SendTextRequest,
    SendTextResponse,
    AudioSendResponse,
    SessionStatusResponse,
    SessionListResponse,
    CloseSessionResponse,
)
from .session_manager import SessionManager
from ..config import PipecatConfig, get_config

# Global config - loaded on startup
config: PipecatConfig = None
session_manager: SessionManager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load config on startup."""
    global config, session_manager

    # Load config from file specified in env var, or default locations
    config_path = os.environ.get("PIPECAT_CONFIG")
    config = get_config(config_path)
    config.setup_logging()

    session_manager = SessionManager(config)

    print(f"Testing API started with config:")
    print(f"  Default bot host: {config.host}")
    print(f"  API host: {config.api_host}:{config.api_port}")

    yield

    # Cleanup on shutdown
    if session_manager:
        await session_manager.close_all()


app = FastAPI(
    title="Pipecat Testing API",
    description="REST API for testing Pipecat voice bot",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/test/session/start", response_model=StartSessionResponse)
async def start_session(request: Optional[StartSessionRequest] = None):
    """Initialize a new test session.

    If bot_host is not provided, uses the default from config.
    """
    # Use request bot_host or fall back to config default
    bot_host = config.host
    if request and request.bot_host:
        bot_host = request.bot_host

    try:
        session_id = await session_manager.create_session(bot_host)
        session = session_manager.get_session(session_id)

        return StartSessionResponse(
            session_id=session_id,
            status="connected",
            ws_url=session.ws_url,
            created_at=session.created_at
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start session: {str(e)}")


@app.post("/test/session/{session_id}/audio", response_model=AudioSendResponse)
async def send_audio(session_id: str, audio_file: UploadFile = File(...)):
    """Send audio file to bot."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        audio_data = await audio_file.read()
        result = await session.send_audio_file(audio_data)
        return AudioSendResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/test/session/{session_id}/text", response_model=SendTextResponse)
async def send_text(session_id: str, request: SendTextRequest):
    """Send text to bot."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        frame_id = await session.send_text(request.text)
        return SendTextResponse(sent=True, frame_id=frame_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/test/session/{session_id}/messages")
async def get_messages(session_id: str, limit: int = 100, since: Optional[float] = None):
    """Get messages received from bot."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = session.get_messages(limit=limit, since=since)

    return {
        "session_id": session_id,
        "messages": messages,
        "total_messages": len(messages)
    }


@app.get("/test/session/{session_id}/status", response_model=SessionStatusResponse)
async def get_status(session_id: str):
    """Get session status."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionStatusResponse(**session.get_status())


@app.delete("/test/session/{session_id}", response_model=CloseSessionResponse)
async def close_session(session_id: str):
    """Close session."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    metrics = await session_manager.close_session(session_id)

    return CloseSessionResponse(
        session_id=session_id,
        status="closed",
        final_metrics=metrics
    )


@app.get("/test/sessions", response_model=SessionListResponse)
async def list_sessions():
    """List all active sessions."""
    sessions = session_manager.list_sessions()
    return SessionListResponse(
        sessions=sessions,
        total_active=len(sessions)
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "config": {
            "default_bot_host": config.host,
            "api_port": config.api_port
        }
    }


@app.get("/config")
async def get_current_config():
    """Get current configuration."""
    return {
        "host": config.host,
        "pipeline_init_delay": config.pipeline_init_delay,
        "max_retries": config.max_retries,
        "session_timeout": config.session_timeout,
        "max_sessions": config.max_sessions
    }


def run_server(config_path: Optional[str] = None):
    """Run the API server with optional config file."""
    import uvicorn

    if config_path:
        os.environ["PIPECAT_CONFIG"] = config_path

    cfg = get_config(config_path)
    uvicorn.run(
        "pipecat_load_tester.api.main:app",
        host=cfg.api_host,
        port=cfg.api_port,
        reload=False
    )


if __name__ == "__main__":
    run_server()
