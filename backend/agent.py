import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ThinkingPart, UserPromptPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

import skills
from config import settings

MAX_HISTORY_MESSAGES = 20


class ModelChoice(StrEnum):
    GPT5_MINI = "gpt-5-mini-2025-08-07"
    GPT54_MINI = "gpt-5.4-mini-2026-03-17"
    GPT54 = "gpt-5.4-2026-03-05"


class ReasoningEffort(StrEnum):
    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


REASONING_METADATA: dict[ReasoningEffort, dict[str, str]] = {
    ReasoningEffort.NONE: {"name": "None", "description": "No reasoning - fastest responses (gpt-5.4 default)"},
    ReasoningEffort.MINIMAL: {"name": "Minimal", "description": "Very light reasoning pass"},
    ReasoningEffort.LOW: {"name": "Low", "description": "Light reasoning for simple multi-step questions"},
    ReasoningEffort.MEDIUM: {"name": "Medium", "description": "Balanced reasoning - model default for gpt-5-mini"},
    ReasoningEffort.HIGH: {"name": "High", "description": "Deep reasoning for complex lore questions"},
    ReasoningEffort.XHIGH: {"name": "xHigh", "description": "Maximum reasoning - slowest but most thorough"},
}


MODEL_METADATA: dict[ModelChoice, dict[str, str]] = {
    ModelChoice.GPT5_MINI: {
        "name": "GPT-5 mini",
        "description": "Fast and efficient - great for everyday lore lookups",
        "color": "#16141a",
        "default_reasoning": ReasoningEffort.MEDIUM,
    },
    ModelChoice.GPT54_MINI: {
        "name": "GPT-5.4 mini",
        "description": "Smarter reasoning for complex or multi-part questions",
        "color": "#7a3a10",
        "default_reasoning": ReasoningEffort.NONE,
    },
    ModelChoice.GPT54: {
        "name": "GPT-5.4",
        "description": "Most capable - best for nuanced analysis and deep lore dives",
        "color": "#6a1010",
        "default_reasoning": ReasoningEffort.NONE,
    },
}


def strip_tool_messages(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Keep only user prompts and final text responses - discard tool calls/returns."""
    clean: list[ModelMessage] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            user_parts = [p for p in msg.parts if isinstance(p, UserPromptPart)]
            if user_parts:
                clean.append(ModelRequest(parts=user_parts))
        elif isinstance(msg, ModelResponse):
            kept_parts = [p for p in msg.parts if isinstance(p, (TextPart, ThinkingPart))]
            if kept_parts:
                clean.append(ModelResponse(parts=kept_parts, model_name=msg.model_name, timestamp=msg.timestamp))
    return clean


class LoreKeeperAgent:
    """Agent that owns session history and active skill state."""

    def __init__(self) -> None:
        self._agent: Agent = create_agent()
        self._sessions: dict[str, list[ModelMessage]] = {}
        self._active_skills: dict[str, str] = {}

    def clear_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._active_skills.pop(session_id, None)

    @asynccontextmanager
    async def chat_stream(
        self,
        session_id: str,
        message: str,
        *,
        model: OpenAIResponsesModel,
        settings: OpenAIResponsesModelSettings,
    ) -> AsyncIterator[Any]:
        """Handle skill detection, system prompt injection, run, history update, and completion detection."""
        # 1. Detect skill command
        user_prompt = message
        if message.startswith("/"):
            parts = message[1:].split(None, 1)
            if parts:
                skill_name = parts[0]
                args = parts[1] if len(parts) > 1 else ""
                result = skills.dispatch(skill_name, args)
                if result.startswith(("Unknown skill:", "Usage:")):
                    user_prompt = result
                else:
                    self._active_skills[session_id] = result
                    user_prompt = f"Start the {skill_name} workflow for: {args}"

        # 2. Inject active skill into system prompt
        active = self._active_skills.get(session_id)
        instructions = f"{SYSTEM_PROMPT}\n\n---\n\n{active}" if active else SYSTEM_PROMPT

        # 3. Trimmed history
        history = self._sessions.get(session_id)
        trimmed = history[-MAX_HISTORY_MESSAGES:] if history and len(history) > MAX_HISTORY_MESSAGES else history

        # 4. Run
        async with self._agent.run_stream(
            user_prompt=user_prompt,
            message_history=trimmed,
            model=model,
            model_settings=settings,
            instructions=instructions,
        ) as stream:
            yield stream

        # 5. Update history
        self._sessions[session_id] = strip_tool_messages(stream.all_messages())

        # 6. Detect [SKILL_COMPLETE] in last response — clear active skill
        if session_id in self._active_skills:
            last = self._sessions[session_id][-1] if self._sessions[session_id] else None
            if isinstance(last, ModelResponse) and any(
                "[SKILL_COMPLETE]" in str(p.content) for p in last.parts if isinstance(p, (TextPart, ThinkingPart))
            ):
                self._active_skills.pop(session_id, None)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def build_model(choice: ModelChoice) -> OpenAIResponsesModel:
    return OpenAIResponsesModel(choice.value, provider=OpenAIProvider(api_key=settings.openai_api_key))


SYSTEM_PROMPT = (
    "You are LoreKeeper, the lore keeper of a Dungeons & Dragons campaign.\n"
    "Answer ONLY from retrieved context. No outside knowledge. No guessing. No making up information.\n"
    f"The ID of the main campaign is {settings.campaign_id}.\n"
    "IDs are 32-character hex strings from Obsidian Portal (found in metadata), NOT names or slugs.\n\n"
    "EXCEPTION - NO RETRIEVAL NEEDED: If the user is clearly just testing connectivity or greeting you "
    "(e.g. 'hello', 'hi', 'test', 'are you working?', 'ping', etc.), respond briefly and naturally "
    "WITHOUT calling any tools or performing any searches.\n\n"
    "MANDATORY RETRIEVAL RULES - follow these EVERY time:\n"
    "1. SEARCH FIRST: Before answering ANY question, call qdrant-find with relevant keywords. "
    "Try multiple search queries with different phrasings to maximize coverage.\n"
    "2. EXPAND INCOMPLETE RESULTS: After qdrant-find, check metadata.chunk_index and metadata.total_chunks "
    "for EACH result. If the result has multiple chunks, call qdrant-expand-context with that document_id and "
    "chunk_index to get the full surrounding content.\n"
    "3. FETCH FULL DOCUMENTS when needed: If the user mentions a specific document or page by name, "
    "or if you need comprehensive information from a document, call qdrant-get-document-chunks "
    "with the document_id from metadata to retrieve the entire document.\n"
    "4. CROSS-REFERENCE: Search for related entities mentioned in results (character names, locations, events) "
    "with additional qdrant-find calls.\n"
    "5. EXPANDING INFO: NEVER say 'no other details were provided' or 'no additional information is available' "
    "without FIRST expanding context on every relevant result and trying alternative search queries.\n\n"
    "If after exhausting all retrieval steps you still cannot find the answer, say so honestly.\n"
    "6. NATURAL LANGUAGE: Do not reference IDs in your response. To let the user search for more context on their "
    "own you can provide the name of the document or page, and a link to it on Obsidian Portal. IDs are only for "
    "retrieval purposes and are not meaningful to the user.\n"
    "7. WRITE VERIFICATION: Before performing any write operations (e.g. creating a new character), MAKE SURE to "
    "check that it does not exist to avoid conflicts.\n"
    "8. USER APPROVAL: Before performing any write operations, ALWAYS ask the user for explicit approval with the "
    "exact details of the operation you intend to perform. Do NOT perform any write operations without explicit "
    "user approval.\n"
    "9. BE CONCISE: When performing write operations be as concise as possible while still providing complete and "
    "accurate information. Avoid repeating the same information.\n"
    "10. OBSIDIAN PORTAL LINKS: When generating content (quest bodies, character bios/descriptions) "
    "that references another entity, use Obsidian Portal wiki-link syntax instead of plain text:\n"
    "    - Characters/items: [[:slug | Display Name]]  (slug from metadata.slug or fetch_characters_tool)\n"
    "    - Pages: [[Page Title | Display Name]]  (title from metadata.title or fetch_wiki_page_tool)\n"
    "    The display name can be any contextually appropriate text (full name, nickname, title, etc.).\n"
    "    Example: [[:allandra-grey | Allandra Grey]], [[Burning Wizard, the | the Burning Wizard]]\n"
    "    If you do not know the slug or title of an entity, look it up via qdrant-find or "
    "fetch_characters_tool before writing the content."
)


def create_agent() -> Agent:
    qdrant_mcp = MCPServerStreamableHTTP(
        url=os.environ.get("QDRANT_MCP_URL", "http://127.0.0.1:8000/mcp"),
        timeout=60,
    )
    obsidian_portal_mcp = MCPServerStreamableHTTP(
        url=os.environ.get("OBSIDIAN_MCP_URL", "http://127.0.0.1:8080/mcp"),
        timeout=60,
    )

    model = build_model(ModelChoice.GPT5_MINI)

    return Agent(
        model=model,
        name="LoreKeeper",
        toolsets=[qdrant_mcp, obsidian_portal_mcp],
        system_prompt=SYSTEM_PROMPT,
    )


async def main() -> None:
    agent = create_agent()

    print("Agent ready. Type your question (or 'exit' to quit):")
    user_input = input("User: ").strip()
    history: list[ModelMessage] | None = None

    while user_input.lower() != "exit":
        if not user_input:
            user_input = input("User: ").strip()
            continue

        try:
            result = await agent.run(
                user_prompt=user_input,
                message_history=(
                    history[-MAX_HISTORY_MESSAGES:] if history and len(history) > MAX_HISTORY_MESSAGES else history
                ),
            )
            history = strip_tool_messages(result.all_messages())
            if hasattr(result, "usage"):
                logger.info("Token usage: %s", result.usage())
            print(f"Agent: {result.output}\n")
        except Exception as e:
            error_msg = f"Error running agent: {e}"
            print(error_msg)
            logger.error(error_msg, exc_info=True)

        user_input = input("User: ").strip()


if __name__ == "__main__":
    asyncio.run(main())
