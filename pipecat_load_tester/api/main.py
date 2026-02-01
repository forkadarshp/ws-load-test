"""FastAPI Testing API for Pipecat voice bot."""
from typing import Optional

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

app = FastAPI(
    title="Pipecat Testing API",
    description="REST API for testing Pipecat voice bot",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

session_manager = SessionManager()


@app.post("/test/session/start", response_model=StartSessionResponse)
async def start_session(request: Optional[StartSessionRequest] = None):
    """Initialize a new test session."""
    bot_host = request.bot_host if request else "localhost:8000"

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
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
