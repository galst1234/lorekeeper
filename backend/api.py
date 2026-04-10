import asyncio
import contextlib
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterable
from dataclasses import dataclass, field
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
    PartEndEvent,
    PartStartEvent,
    ThinkingPartDelta,
    ToolCallPartDelta,
)
from pydantic_ai.messages import TextPart, ThinkingPart, ToolCallPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings

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


@dataclass
class _StreamState:
    """Mutable state shared across all event_stream_handler calls for one agent run."""

    block_counter: list[int] = field(default_factory=lambda: [0])
    # pydantic-ai part index -> (block_kind, sse_block_index, tool_call_id)
    open_parts: dict[int, tuple[str, int, str]] = field(default_factory=dict)
    # tool_call_id -> (tool_name, sse_block_index) — populated when tool_call_end fires
    tcid_to_info: dict[str, tuple[str, int]] = field(default_factory=dict)


async def _collect_agent_events(  # noqa: C901, PLR0912
    queue: asyncio.Queue[str | None],
    _ctx: object,
    events: AsyncIterable[AgentStreamEvent],
    state: _StreamState,
) -> None:
    """Map pydantic-ai agent stream events to SSE JSON messages on queue."""
    async for event in events:
        if isinstance(event, PartStartEvent):
            if isinstance(event.part, ThinkingPart):
                sse_idx = state.block_counter[0]
                state.open_parts[event.index] = ("thinking", sse_idx, "")
                await queue.put(json.dumps({"type": "thinking_start", "index": sse_idx}))
                state.block_counter[0] += 1
                if event.part.content:
                    await queue.put(
                        json.dumps({"type": "thinking_delta", "index": sse_idx, "delta": event.part.content}),
                    )
            elif isinstance(event.part, ToolCallPart):
                # Close any open thinking blocks
                for pai_idx, (bt, si, _) in list(state.open_parts.items()):
                    if bt == "thinking":
                        await queue.put(json.dumps({"type": "thinking_end", "index": si}))
                        del state.open_parts[pai_idx]
                state.open_parts[event.index] = ("tool_call", state.block_counter[0], event.part.tool_call_id)
                await queue.put(
                    json.dumps({
                        "type": "tool_call_start",
                        "index": state.block_counter[0],
                        "tool_name": event.part.tool_name,
                    }),
                )
                state.block_counter[0] += 1
            elif isinstance(event.part, TextPart):
                # Close any remaining open blocks before text begins
                for bt, si, _ in state.open_parts.values():
                    await queue.put(json.dumps({"type": f"{bt}_end", "index": si}))
                state.open_parts.clear()

        elif isinstance(event, PartEndEvent):
            if event.index in state.open_parts and state.open_parts[event.index][0] == "thinking":
                _, si, _ = state.open_parts.pop(event.index)
                await queue.put(json.dumps({"type": "thinking_end", "index": si}))

        elif isinstance(event, PartDeltaEvent):
            if isinstance(event.delta, ThinkingPartDelta) and event.index in state.open_parts:
                _, sse_idx, _ = state.open_parts[event.index]
                if event.delta.content_delta:
                    await queue.put(
                        json.dumps({
                            "type": "thinking_delta",
                            "index": sse_idx,
                            "delta": event.delta.content_delta,
                        }),
                    )
            elif (
                isinstance(event.delta, ToolCallPartDelta)
                and event.delta.args_delta
                and event.index in state.open_parts
            ):
                _, sse_idx, _ = state.open_parts[event.index]
                await queue.put(
                    json.dumps(
                        {
                            "type": "tool_call_args_delta",
                            "index": sse_idx,
                            "delta": str(event.delta.args_delta),
                        },
                    ),
                )

        elif isinstance(event, FunctionToolCallEvent):
            # Close the matching open tool_call part and record (tool_name, sse_index) for pairing
            for pai_idx, (bt, si, tcid) in list(state.open_parts.items()):
                if bt == "tool_call" and tcid == event.part.tool_call_id:
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
                    state.tcid_to_info[event.part.tool_call_id] = (event.part.tool_name, si)
                    del state.open_parts[pai_idx]
                    break

        elif isinstance(event, FunctionToolResultEvent):
            info = state.tcid_to_info.get(event.tool_call_id)
            if info is None:
                logger.warning(
                    "tool_response for unknown tool_call_id %s — emitting with call_index=-1",
                    event.tool_call_id,
                )
            tool_name = info[0] if info else event.tool_call_id
            call_index = info[1] if info else -1
            await queue.put(
                json.dumps({
                    "type": "tool_response",
                    "tool_name": tool_name,
                    "call_index": call_index,
                    "content": str(event.result.content),
                }),
            )

    # Close any remaining open parts at stream end
    for bt, si, _ in state.open_parts.values():
        await queue.put(json.dumps({"type": f"{bt}_end", "index": si}))


async def _run_agent_task(  # noqa: PLR0913
    agent_instance: LoreKeeperAgent,
    queue: asyncio.Queue[str | None],
    *,
    session_id: str,
    message: str,
    run_model: OpenAIResponsesModel,
    run_settings: OpenAIResponsesModelSettings,
) -> None:
    """Drive agent stream to completion; puts SSE payloads on queue, sentinel in finally."""

    state = _StreamState()

    async def _handler(_ctx: object, evts: AsyncIterable[AgentStreamEvent]) -> None:
        await _collect_agent_events(queue, _ctx, evts, state)

    try:
        async with agent_instance.chat_stream(
            session_id,
            message,
            model=run_model,
            model_settings=run_settings,
            event_stream_handler=_handler,
        ) as stream:
            async for delta in stream.stream_text(delta=True):
                if delta:
                    await queue.put(json.dumps({"type": "text_delta", "delta": delta}))
    except Exception as e:
        logger.error("Stream error: %s", e, exc_info=True)
        await queue.put(json.dumps({"type": "error", "error": str(e)}))
    finally:
        await queue.put(None)


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    session_id = req.session_id or str(uuid.uuid4())
    run_model = build_model(req.model)
    run_settings = OpenAIResponsesModelSettings(
        openai_reasoning_effort=req.reasoning_effort.value,
        openai_reasoning_summary="concise",
    )

    async def event_stream() -> AsyncGenerator[str]:
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=128)
        agent_task = asyncio.create_task(
            _run_agent_task(
                agent,
                queue,
                session_id=session_id,
                message=req.message,
                run_model=run_model,
                run_settings=run_settings,
            ),
        )
        error_occurred = False
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                try:
                    if json.loads(item).get("type") == "error":
                        error_occurred = True
                except Exception:
                    pass
                yield f"data: {item}\n\n"
        finally:
            agent_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await agent_task
        if not error_occurred:
            yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    agent.clear_session(session_id)
    return {"status": "cleared"}
