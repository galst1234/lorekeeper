import asyncio
import logging
import os

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider

from config import settings

MAX_HISTORY_MESSAGES = 20


def strip_tool_messages(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Keep only user prompts and final text responses — discard tool calls/returns."""
    clean: list[ModelMessage] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            user_parts = [p for p in msg.parts if isinstance(p, UserPromptPart)]
            if user_parts:
                clean.append(ModelRequest(parts=user_parts))
        elif isinstance(msg, ModelResponse):
            text_parts = [p for p in msg.parts if isinstance(p, TextPart)]
            if text_parts:
                clean.append(ModelResponse(parts=text_parts, model_name=msg.model_name, timestamp=msg.timestamp))
    return clean


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_agent(local: bool = False) -> Agent:
    system_prompt = (
        "You are LoreKeeper, the lore keeper of a Dungeons & Dragons campaign.\n"
        "Answer ONLY from retrieved context. No outside knowledge. No guessing. No making up information.\n"
        f"The ID of the main campaign is {settings.campaign_id}.\n"
        "IDs are 32-character hex strings from Obsidian Portal (found in metadata), NOT names or slugs.\n\n"
        "EXCEPTION — NO RETRIEVAL NEEDED: If the user is clearly just testing connectivity or greeting you "
        "(e.g. 'hello', 'hi', 'test', 'are you working?', 'ping', etc.), respond briefly and naturally "
        "WITHOUT calling any tools or performing any searches.\n\n"
        "MANDATORY RETRIEVAL RULES — follow these EVERY time:\n"
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

    qdrant_mcp = MCPServerStreamableHTTP(
        url=os.environ.get("QDRANT_MCP_URL", "http://127.0.0.1:8000/mcp"),
        timeout=60,
    )
    obsidian_portal_mcp = MCPServerStreamableHTTP(
        url=os.environ.get("OBSIDIAN_MCP_URL", "http://127.0.0.1:8080/mcp"),
        timeout=60,
    )

    if local:
        # noinspection PyTypeChecker
        model = OpenAIChatModel(
            model_name=settings.ollama_model,
            provider=OllamaProvider(base_url=f"{settings.ollama_url}/v1"),
        )
    else:
        model = OpenAIChatModel(
            model_name=settings.openai_model,
            provider=OpenAIProvider(api_key=settings.openai_api_key),
        )

    return Agent(
        model=model,
        toolsets=[qdrant_mcp, obsidian_portal_mcp],
        system_prompt=system_prompt,
    )


async def main(local: bool = False) -> None:
    agent = create_agent(local)

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
