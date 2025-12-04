import asyncio

from pydantic_ai import (
    Agent,
)
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.providers.ollama import OllamaProvider

from config import GROQ_API_KEY, GROQ_MODEL, OLLAMA_MODEL, OLLAMA_URL


async def main(local: bool = False) -> None:
    # ruff: noqa: E501
    system_prompt = (
        "You are LoreKeeper, you are the lore keeper of a Dungeons & Dragons campaign. "
        "You must answer ONLY using the information provided in the context below, or get more context via tool calls. "
        "If the answer is not explicitly stated in the context you have, respond with 'I don't know based on the provided information.' "
        "Do NOT use any outside knowledge, do NOT guess, and do NOT make up information. "
        "Always base your answer strictly on the context. "
        "You may call tools multiple times to get more context if needed. "
        "After each tool call, review the new information and decide whether additional searches would improve your answer. "
        "Stop only when you are confident you have enough information to provide a complete and accurate answer, or say you don't know. "
        "For non-trivial questions, you should usually perform at least 2-3 tool calls with different queries before answering, unless the first result is obviously sufficient. "
        "When you want to use a tool, you MUST respond with a function/tool call, not plain text or JSON. Do NOT describe the tool call in text. Only use the function/tool call format. "
        "When you respond with your final answer, there is no need to start with explanatory text (e.g. Based on the provided information) just provide the answer directly. "
        "The data you have access to is from a Qdrant vector database containing session summaries and wiki pages of the Dungeons & Dragons campaign. "
        "In the Qdrant vector database you can differentiate between session summaries and wiki pages based on the 'type' field in the metadata: "
        "session summaries have type 'Post' and wiki pages have type 'WikiPage'. "
        "The campaign is dozens of sessions long, so for context retrieval you should usually get context from multiple session summaries and wiki pages to ensure comprehensive coverage of the lore. "
        "The more context you gather from different summaries and wiki pages, the better your answer will be. "
        "Always aim to gather diverse pieces of information from multiple sources before answering. "
        "You must always make at least two tool calls with different queries before answering, unless the answer is trivial and obvious from the first result. "
    )

    qdrant_mcp = MCPServerStreamableHTTP(
        url="http://127.0.0.1:8000/mcp",
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
        toolsets=[qdrant_mcp],
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

            print(f"Agent: {result.output}\n")
        except Exception as e:
            print(f"Error running agent: {e}")

        user_input = input("User: ").strip()


if __name__ == "__main__":
    asyncio.run(main())
