import asyncio
import contextlib
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterable
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ThinkingPartDelta,
    ToolCallPartDelta,
)
from pydantic_ai.messages import TextPart, ThinkingPart, ToolCallPart
from pydantic_ai.models.openai import OpenAIResponsesModelSettings

from agent import (
    MODEL_METADATA,
    REASONING_METADATA,
    LoreKeeperAgent,
    ModelChoice,
    ReasoningEffort,
    build_model,
)
from config import settings

logger = logging.getLogger(__name__)

app = FastAPI(title="LoreKeeper API")

app.add_middleware(
    CORSMiddleware,  # type: ignore[arg-type]
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = LoreKeeperAgent()


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""
    model: ModelChoice = ModelChoice.GPT5_MINI
    reasoning_effort: ReasoningEffort = ReasoningEffort.MEDIUM


@app.get("/api/models")
async def get_models() -> list[dict[str, str]]:
    return [{"id": m.value, **MODEL_METADATA[m]} for m in ModelChoice]


@app.get("/api/reasoning-levels")
async def get_reasoning_levels() -> list[dict[str, str]]:
    return [{"id": r.value, **REASONING_METADATA[r]} for r in ReasoningEffort]


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
async def chat(req: ChatRequest) -> StreamingResponse:  # noqa: C901, PLR0915
    session_id = req.session_id or str(uuid.uuid4())
    run_model = build_model(req.model)
    run_settings = OpenAIResponsesModelSettings(openai_reasoning_effort=req.reasoning_effort.value)

    async def event_stream() -> AsyncGenerator[str]:  # noqa: C901, PLR0915
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def handle_events(  # noqa: C901, PLR0912
            _ctx: object,
            events: AsyncIterable[AgentStreamEvent],
        ) -> None:
            # open_parts: pydantic-ai part index -> (block_kind, sse_block_index)
            open_parts: dict[int, tuple[str, int]] = {}
            # tool_call_id -> tool_name, for matching FunctionToolResultEvent
            tool_call_ids: dict[str, str] = {}
            next_block = 0

            async for event in events:
                if isinstance(event, PartStartEvent):
                    if isinstance(event.part, ThinkingPart):
                        open_parts[event.index] = ("thinking", next_block)
                        await queue.put(json.dumps({"type": "thinking_start", "index": next_block}))
                        next_block += 1
                    elif isinstance(event.part, ToolCallPart):
                        # Close any open thinking blocks
                        for pai_idx, (bt, si) in list(open_parts.items()):
                            if bt == "thinking":
                                await queue.put(json.dumps({"type": "thinking_end", "index": si}))
                                del open_parts[pai_idx]
                        open_parts[event.index] = ("tool_call", next_block)
                        await queue.put(
                            json.dumps({
                                "type": "tool_call_start",
                                "index": next_block,
                                "tool_name": event.part.tool_name,
                            }),
                        )
                        next_block += 1
                    elif isinstance(event.part, TextPart):
                        # New model response: close any remaining open blocks
                        for bt, si in open_parts.values():
                            await queue.put(json.dumps({"type": f"{bt}_end", "index": si}))
                        open_parts.clear()

                elif isinstance(event, PartDeltaEvent):
                    if isinstance(event.delta, ThinkingPartDelta):
                        if event.index in open_parts:
                            _, sse_idx = open_parts[event.index]
                            await queue.put(
                                json.dumps({
                                    "type": "thinking_delta",
                                    "index": sse_idx,
                                    "delta": event.delta.content_delta,
                                }),
                            )
                    elif isinstance(event.delta, ToolCallPartDelta) and event.delta.args_delta:
                        if event.index in open_parts:
                            _, sse_idx = open_parts[event.index]
                            await queue.put(
                                json.dumps(
                                    {
                                        "type": "tool_call_args_delta",
                                        "index": sse_idx,
                                        "delta": str(event.delta.args_delta),
                                    },
                                ),
                            )
                    elif isinstance(event.delta, TextPartDelta):
                        await queue.put(json.dumps({"type": "text_delta", "delta": event.delta.content_delta}))

                elif isinstance(event, FunctionToolCallEvent):
                    tool_call_ids[event.part.tool_call_id] = event.part.tool_name
                    # Close the matching open tool_call part
                    for pai_idx, (bt, si) in list(open_parts.items()):
                        if bt == "tool_call":
                            try:
                                complete_args = (
                                    json.dumps(event.part.args, indent=2)
                                    if isinstance(event.part.args, dict)
                                    else str(event.part.args)
                                )
                            except Exception:
                                complete_args = str(event.part.args)
                            await queue.put(
                                json.dumps({"type": "tool_call_end", "index": si, "complete_args": complete_args}),
                            )
                            del open_parts[pai_idx]
                            break

                elif isinstance(event, FunctionToolResultEvent):
                    tool_name = tool_call_ids.get(event.tool_call_id, event.tool_call_id)
                    await queue.put(
                        json.dumps({
                            "type": "tool_response",
                            "tool_name": tool_name,
                            "content": str(event.result.content),
                        }),
                    )

            # Close any remaining open parts at stream end
            for bt, si in open_parts.values():
                await queue.put(json.dumps({"type": f"{bt}_end", "index": si}))

            await queue.put(None)  # sentinel

        async def run_agent() -> None:
            try:
                async with agent.chat_stream(
                    session_id,
                    req.message,
                    model=run_model,
                    model_settings=run_settings,
                    event_stream_handler=handle_events,
                ) as stream:
                    # Drive the run to completion; text is captured via TextPartDelta events
                    async for _ in stream.stream_text(delta=True):
                        pass
            except Exception as e:
                logger.error(f"Stream error: {e}", exc_info=True)
                await queue.put(json.dumps({"type": "error", "error": str(e)}))
                await queue.put(None)

        agent_task = asyncio.create_task(run_agent())

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {item}\n\n"
        finally:
            agent_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await agent_task

        yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    agent.clear_session(session_id)
    return {"status": "cleared"}
