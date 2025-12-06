import asyncio
import logging

from pydantic_ai import (
    Agent,
)
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.providers.ollama import OllamaProvider

from config import CAMPAIGN_ID, GROQ_API_KEY, GROQ_MODEL, OLLAMA_MODEL, OLLAMA_URL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main(local: bool = False) -> None:
    # ruff: noqa: E501
    system_prompt = (
        "You are LoreKeeper, you are the lore keeper of a Dungeons & Dragons campaign. "
        "You must answer ONLY using the information provided in the context below, and get more context via tool calls. "
        "Do NOT use any outside knowledge, do NOT guess, and do NOT make up information. "
        "Always base your answer strictly on the context. "
        "You may use the available tools to get more context. "
        "After using tools and reviewing the results, decide whether additional searches would improve your answer. "
        "Stop only when you are confident you have enough information to provide a complete and accurate answer, or say you don't know. "
        "Whenever a question requires campaign lore, first call the appropriate search tool to retrieve relevant session summaries, wiki pages, and characters before answering. "
        f"The ID of the main campaign you are working with is {CAMPAIGN_ID}. "
        "IDs are NOT the names, titles, or slugs, but the unique identifiers assigned by Obsidian Portal, which are a 32 character hex strings that can be found in the metadata of qdrant points. "
    )

    qdrant_mcp = MCPServerStreamableHTTP(
        url="http://127.0.0.1:8000/mcp",
        timeout=60,
    )
    obsidian_portal_mcp = MCPServerStreamableHTTP(
        url="http://127.0.0.1:8080/mcp",
        timeout=60,
    )

    if local:
        # noinspection PyTypeChecker
        model = OpenAIChatModel(
            model_name=OLLAMA_MODEL,
            provider=OllamaProvider(base_url=f"{OLLAMA_URL}/v1"),
        )
    else:
        # noinspection PyTypeChecker
        model = GroqModel(  # type: ignore
            model_name=GROQ_MODEL,
            provider=GroqProvider(
                api_key=GROQ_API_KEY,
            ),
        )

    agent = Agent(
        model=model,
        toolsets=[qdrant_mcp, obsidian_portal_mcp],
        system_prompt=system_prompt,
    )
    print("Agent ready. Type your question (or 'exit' to quit):")
    user_input = input("User: ").strip()
    history = None
    while user_input.lower() != "exit":
        if not user_input:
            user_input = input("User: ").strip()
            continue

        try:
            result = await agent.run(
                user_prompt=user_input,
                message_history=history,
            )
            history = result.all_messages()
            logger.debug(f"Agent interaction:\n{result.all_messages()}")

            print(f"Agent: {result.output}\n")
        except Exception as e:
            print(f"Error running agent: {e}")

        user_input = input("User: ").strip()


if __name__ == "__main__":
    asyncio.run(main())
