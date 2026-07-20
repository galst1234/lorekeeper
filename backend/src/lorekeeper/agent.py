import asyncio
import logging
import os
from collections.abc import AsyncIterable, AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Any

import openai
from pydantic_ai import Agent, AgentStreamEvent
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.openai import OpenAICompaction, OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from lorekeeper import skills
from lorekeeper.config import settings

type EventStreamHandler = Callable[[Any, AsyncIterable[AgentStreamEvent]], Coroutine[Any, Any, None]] | None


class ModelChoice(StrEnum):
    GPT56_LUNA = "gpt-5.6-luna"
    GPT56_TERRA = "gpt-5.6-terra"
    GPT56_SOL = "gpt-5.6-sol"


class ReasoningEffort(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


REASONING_METADATA: dict[ReasoningEffort, dict[str, str]] = {
    ReasoningEffort.NONE: {"name": "None", "description": "No reasoning - fastest responses"},
    ReasoningEffort.LOW: {"name": "Low", "description": "Light reasoning for simple multi-step questions"},
    ReasoningEffort.MEDIUM: {"name": "Medium", "description": "Balanced reasoning for harder questions"},
    ReasoningEffort.HIGH: {"name": "High", "description": "Deep reasoning for complex lore questions"},
    ReasoningEffort.XHIGH: {"name": "xHigh", "description": "Very deep reasoning for the hardest questions"},
    ReasoningEffort.MAX: {"name": "Max", "description": "Maximum reasoning - slowest but most thorough"},
}


MODEL_METADATA: dict[ModelChoice, dict[str, str]] = {
    ModelChoice.GPT56_LUNA: {
        "name": "GPT-5.6 luna $",
        "description": "Fast and efficient - great for everyday lore lookups",
        "color": "#16141a",
        "default_reasoning": ReasoningEffort.LOW,
    },
    ModelChoice.GPT56_TERRA: {
        "name": "GPT-5.6 terra $x2.5",
        "description": "Smarter reasoning for complex or multi-part questions",
        "color": "#7a3a10",
        "default_reasoning": ReasoningEffort.MEDIUM,
    },
    ModelChoice.GPT56_SOL: {
        "name": "GPT-5.6 sol $x5",
        "description": "Most capable - best for nuanced analysis and deep lore dives",
        "color": "#FF0000",
        "default_reasoning": ReasoningEffort.MEDIUM,
    },
}


class LoreKeeperAgent:
    """Agent that owns session history and active skill state."""

    def __init__(self) -> None:
        self._previous_response_ids: dict[str, str] = {}
        self._active_skills: dict[str, str] = {}

    def clear_session(self, session_id: str) -> None:
        self._previous_response_ids.pop(session_id, None)
        self._active_skills.pop(session_id, None)

    def _resolve_user_prompt(self, session_id: str, message: str) -> str:
        """Detect /skill commands, activate skill if valid, return the user prompt to send."""
        if not message.startswith("/"):
            return message
        parts = message[1:].split(None, 1)
        if not parts:
            return message
        skill_name = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        result = skills.dispatch(skill_name, args)
        if result.startswith(("Unknown skill:", "Usage:")):
            return result
        self._active_skills[session_id] = result
        return f"Start the {skill_name} workflow for: {args}"

    def _build_instructions(self, session_id: str) -> str:
        """Return system prompt, with active skill injected if one is running."""
        active = self._active_skills.get(session_id)
        return f"{SYSTEM_PROMPT}\n\n---\n\n{active}" if active else SYSTEM_PROMPT

    def _build_model_settings(
        self,
        session_id: str,
        model_settings: OpenAIResponsesModelSettings,
    ) -> OpenAIResponsesModelSettings:
        """Use OpenAI server-side response chaining when a previous response is available."""
        previous_response_id = self._previous_response_ids.get(session_id)
        if not previous_response_id:
            return model_settings
        return OpenAIResponsesModelSettings(**{**model_settings, "openai_previous_response_id": previous_response_id})

    def _finalize(self, session_id: str, messages: list[ModelMessage]) -> None:
        """Store the latest OpenAI response ID. Clear active skill when the workflow completes."""
        last = next((m for m in reversed(messages) if isinstance(m, ModelResponse)), None)
        if isinstance(last, ModelResponse) and last.provider_response_id:
            self._previous_response_ids[session_id] = last.provider_response_id
        else:
            self._previous_response_ids.pop(session_id, None)
        if session_id not in self._active_skills:
            return
        if isinstance(last, ModelResponse) and any(
            "[SKILL_COMPLETE]" in str(p.content) for p in last.parts if isinstance(p, TextPart)
        ):
            self._active_skills.pop(session_id, None)

    @asynccontextmanager
    async def chat_stream(
        self,
        session_id: str,
        message: str,
        *,
        model: OpenAIResponsesModel,
        model_settings: OpenAIResponsesModelSettings,
        event_stream_handler: EventStreamHandler = None,
    ) -> AsyncIterator[Any]:
        """Stream a chat response, handling skill dispatch and history management."""
        async with create_agent().run_stream(
            user_prompt=self._resolve_user_prompt(session_id, message),
            model=model,
            model_settings=self._build_model_settings(session_id, model_settings),
            instructions=self._build_instructions(session_id),
            event_stream_handler=event_stream_handler,
        ) as stream:
            try:
                yield stream
            finally:
                self._finalize(session_id, stream.all_messages())


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def build_model(choice: ModelChoice) -> OpenAIResponsesModel:
    # Flex-tier requests are queued and can run well past the SDK's 10-minute default;
    # OpenAI recommends up to 15 minutes. See https://developers.openai.com/api/docs/guides/flex-processing
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key, max_retries=5, timeout=900)
    return OpenAIResponsesModel(
        choice.value,
        provider=OpenAIProvider(openai_client=client),
        settings=OpenAIResponsesModelSettings(openai_service_tier="flex"),
    )


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

    model = build_model(ModelChoice.GPT56_LUNA)

    return Agent(
        model=model,
        name="LoreKeeper",
        toolsets=[qdrant_mcp, obsidian_portal_mcp],
        capabilities=[OpenAICompaction()],
    )


async def main() -> None:
    agent = create_agent()

    print("Agent ready. Type your question (or 'exit' to quit):")
    user_input = input("User: ").strip()
    while user_input.lower() != "exit":
        if not user_input:
            user_input = input("User: ").strip()
            continue

        try:
            result = await agent.run(
                user_prompt=user_input,
                instructions=SYSTEM_PROMPT,
            )
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
