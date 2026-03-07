import asyncio
import logging
import os

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider

from config import CAMPAIGN_ID, OLLAMA_MODEL, OLLAMA_URL, OPENAI_API_KEY, OPENAI_MODEL

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
        "You are LoreKeeper, the lore keeper of a Dungeons & Dragons campaign. "
        "Answer ONLY from retrieved context. No outside knowledge. No guessing. No making up information. "
        f"The ID of the main campaign is {CAMPAIGN_ID}. "
        "IDs are 32-character hex strings from Obsidian Portal (found in metadata), NOT names or slugs.\n\n"
        "MANDATORY RETRIEVAL RULES — follow these EVERY time:\n"
        "1. SEARCH FIRST: Before answering ANY question, call qdrant-find with relevant keywords. "
        "Try multiple search queries with different phrasings to maximize coverage.\n"
        "2. EXPAND INCOMPLETE RESULTS: After qdrant-find, check metadata.chunk_index and metadata.total_chunks "
        "for EACH result. If a result is relevant and chunk_index > 0 OR chunk_index < total_chunks - 1, "
        "you MUST call qdrant-expand-context with that document_id and chunk_index to get surrounding chunks. "
        "Do NOT skip this step.\n"
        "3. FETCH FULL DOCUMENTS when needed: If the user mentions a specific document or page by name, "
        "or if you need comprehensive information from a document, call qdrant-get-document-chunks "
        "with the document_id from metadata to retrieve the entire document.\n"
        "4. CROSS-REFERENCE: Search for related entities mentioned in results (character names, locations, events) "
        "with additional qdrant-find calls.\n"
        "5. NEVER say 'no other details were provided' or 'no additional information is available' "
        "without FIRST expanding context on every relevant result and trying alternative search queries.\n\n"
        "If after exhausting all retrieval steps you still cannot find the answer, say so honestly.\n"
        "6. Do not reference IDs in your response. To let the user search for more context on their own you can provide"
        "the name of the document or page, and a link to it on Obsidian Portal. IDs are only for retrieval purposes and"
        " are not meaningful to the user."
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
            model_name=OLLAMA_MODEL,
            provider=OllamaProvider(base_url=f"{OLLAMA_URL}/v1"),
        )
    else:
        model = OpenAIChatModel(
            model_name=OPENAI_MODEL,
            provider=OpenAIProvider(api_key=OPENAI_API_KEY),
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
