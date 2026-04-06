import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai.messages import ModelMessage

from agent import MAX_HISTORY_MESSAGES, MODEL_METADATA, ModelChoice, create_agent, strip_tool_messages
from config import settings

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
    model: ModelChoice = ModelChoice.GPT5_MINI


@app.get("/api/models")
async def get_models() -> list[dict[str, str]]:
    return [{"id": m.value, **MODEL_METADATA[m]} for m in ModelChoice]


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/last-fetched")
async def last_fetched() -> dict:
    p = settings.data_dir / "last_fetched.json"
    if not p.exists():
        return {"fetched_at": None}
    return json.loads(p.read_text(encoding="utf-8"))


async def _run_fetch() -> None:
    proc = await asyncio.create_subprocess_exec(
        "python",
        "obsidian_portal/fetcher.py",
        cwd="/app",
        env={**os.environ, "PYTHONPATH": "/app"},
    )
    exit_code = await proc.wait()
    if exit_code == 0:
        logger.info("Fetcher completed successfully")
    else:
        logger.error("Fetcher exited with code %d", exit_code)


_fetch_tasks: set[asyncio.Task] = set()


def _get_next_allowed_at() -> datetime | None:
    p = settings.data_dir / "last_fetched.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    fetched_at = data.get("fetched_at")
    if not fetched_at:
        return None
    last_dt = datetime.fromisoformat(fetched_at)
    return last_dt + timedelta(hours=1)


@app.get("/api/fetch-status")
async def fetch_status() -> dict:
    running = bool(_fetch_tasks)
    next_allowed_at = None
    next_dt = _get_next_allowed_at()
    if next_dt and next_dt > datetime.now(tz=UTC):
        next_allowed_at = next_dt.isoformat()
    return {"running": running, "next_allowed_at": next_allowed_at}


@app.post("/api/fetch", status_code=202)
async def trigger_fetch() -> dict[str, str]:
    if _fetch_tasks:
        return {"status": "running"}

    next_dt = _get_next_allowed_at()
    if next_dt and next_dt > datetime.now(tz=UTC):
        return {"status": "too_soon", "next_allowed_at": next_dt.isoformat()}

    task = asyncio.create_task(_run_fetch())
    _fetch_tasks.add(task)
    task.add_done_callback(_fetch_tasks.discard)
    return {"status": "started"}


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
                model=req.model,
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
