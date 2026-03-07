import json
import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai.messages import ModelMessage

from agent import MAX_HISTORY_MESSAGES, create_agent, strip_tool_messages

logger = logging.getLogger(__name__)

app = FastAPI(title="LoreKeeper API")

app.add_middleware(
    CORSMiddleware,  # type: ignore[arg-type]
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = create_agent()
sessions: dict[str, list[ModelMessage]] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    session_id = req.session_id or str(uuid.uuid4())
    history = sessions.get(session_id, [])

    trimmed = history[-MAX_HISTORY_MESSAGES:] if len(history) > MAX_HISTORY_MESSAGES else history

    async def event_stream() -> AsyncGenerator[str]:
        try:
            async with agent.run_stream(
                user_prompt=req.message,
                message_history=trimmed,
            ) as stream:
                async for delta in stream.stream_text(delta=True):
                    yield f"data: {json.dumps({'delta': delta})}\n\n"

                new_history = strip_tool_messages(stream.all_messages())
                sessions[session_id] = new_history

        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    sessions.pop(session_id, None)
    return {"status": "cleared"}
