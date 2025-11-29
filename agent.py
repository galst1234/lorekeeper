import asyncio

from agents import Agent, Runner, set_default_openai_api, set_default_openai_client, set_tracing_disabled
from agents.mcp import MCPServerStreamableHttp, MCPServerStreamableHttpParams
from openai import AsyncOpenAI

from config import OLLAMA_MODEL, OLLAMA_URL

set_tracing_disabled(True)
set_default_openai_api("chat_completions")

set_default_openai_client(
    AsyncOpenAI(
        base_url=f"{OLLAMA_URL}/v1",
        api_key="ollama",
    )
)


async def main():
    system_prompt = (
        "You are the lore keeper of a Dungeons & Dragons campaign. "
        "You must answer ONLY using the information provided in the context below. "
        "If the answer is not explicitly stated in the context, respond with 'I don't know based on the provided information.' "
        "Do NOT use any outside knowledge, do NOT guess, and do NOT make up information. "
        "Always base your answer strictly on the context."
    )

    async with MCPServerStreamableHttp(
            name="qdrant-mcp",
            params=MCPServerStreamableHttpParams(
                url="http://127.0.0.1:8000/mcp",
                timeout=60,
            ),
            cache_tools_list=True,
    ) as qdrant_mcp:
        agent = Agent(
            name="Lorekeeper",
            mcp_servers=[qdrant_mcp],
            model=OLLAMA_MODEL,
            instructions=system_prompt,
        )
        print("Agent ready. Type your question (or 'exit' to quit):")
        while True:
            user_input = input("User: ").strip()
            if user_input.lower() == "exit":
                break

            try:
                result = await Runner.run(agent, user_input)
                print("\nAgent:", result.final_output)
            except Exception as e:
                print(f"Error running agent: {e}")


if __name__ == "__main__":
    asyncio.run(main())
