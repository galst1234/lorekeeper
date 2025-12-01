import asyncio

from agents import Agent, ItemHelpers, Runner, set_default_openai_api, set_default_openai_client, set_tracing_disabled
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
        "You must answer ONLY using the information provided in the context below, or get more context via tool calls. "
        "If the answer is not explicitly stated in the context you have, respond with 'I don't know based on the provided information.' "
        "Do NOT use any outside knowledge, do NOT guess, and do NOT make up information. "
        "Always base your answer strictly on the context."
        "You may call tools multiple times to get more context if needed."
        "After each tool call, review the new information and decide whether additional searches would improve your answer."
        "Stop only when you are confident you have enough information to provide a complete and accurate answer, or say you don't know."
        "For non-trivial questions, you should usually perform at least 2–3 tool calls with different queries before answering, unless the first result is obviously sufficient"
        "When you want to use a tool, you MUST respond with a function/tool call, not plain text or JSON. Do NOT describe the tool call in text. Only use the function/tool call format."
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
            reset_tool_choice=False,
        )
        print("Agent ready. Type your question (or 'exit' to quit):")
        while True:
            user_input = input("User: ").strip()
            if user_input.lower() == "exit":
                break

            try:
                result_streaming = Runner.run_streamed(agent, user_input, max_turns=10)
                print("Run started. Streaming response:\n")
                async for event in result_streaming.stream_events():
                    print(f"[EVENT] {repr(event)}")
                    if event.type == "run_item_stream_event":
                        item = event.item
                        if item.type == "message_output_item":
                            # partial or complete messages
                            text = ItemHelpers.text_message_output(item)
                            print(f"[MESSAGE] {text}")
                        elif item.type == "tool_call_item":
                            print(f"[TOOL CALL] {item.raw_item}")
                        elif item.type == "tool_call_output_item":
                            print(f"[TOOL RESULT] {str(item.output)[:200]!r}")

                print("\nAgent:", result_streaming.final_output)
            except Exception as e:
                print(f"Error running agent: {e}")


if __name__ == "__main__":
    asyncio.run(main())
