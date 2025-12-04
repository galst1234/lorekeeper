import asyncio

from pydantic_ai import (
    Agent,
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ThinkingPartDelta,
    ToolCallPartDelta,
)
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider

from config import OLLAMA_MODEL, OLLAMA_URL


async def main() -> None:  # noqa: C901, PLR0912, PLR0915
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
    # noinspection PyTypeChecker
    ollama_model = OpenAIChatModel(
        model_name=OLLAMA_MODEL,
        provider=OllamaProvider(base_url=f"{OLLAMA_URL}/v1"),
    )
    agent = Agent(
        model=ollama_model,
        toolsets=[qdrant_mcp],
        system_prompt=system_prompt,
    )
    print("Agent ready. Type your question (or 'exit' to quit):")
    user_input = input("User: ").strip()
    while user_input.lower() != "exit":  # noqa: PLR1702
        if not user_input:
            user_input = input("User: ").strip()
            continue

        try:
            async with agent.iter(user_input) as run:
                async for node in run:
                    if Agent.is_user_prompt_node(node):
                        # A user prompt node => The user has provided input
                        print(f"=== UserPromptNode: {node.user_prompt} ===")
                    elif Agent.is_model_request_node(node):
                        # A model request node => We can stream tokens from the model's request
                        print("=== ModelRequestNode: streaming partial request tokens ===")
                        async with node.stream(run.ctx) as request_stream:
                            final_result_found = False
                            async for event in request_stream:
                                if isinstance(event, PartStartEvent):
                                    print(f"[Request] Starting part {event.index}: {event.part!r}")
                                elif isinstance(event, PartDeltaEvent):
                                    if isinstance(event.delta, TextPartDelta):
                                        print(
                                            f"[Request] Part {event.index} text delta: {event.delta.content_delta!r}",
                                        )
                                    elif isinstance(event.delta, ThinkingPartDelta):
                                        print(
                                            f"[Request] Part {event.index} thinking delta: {event.delta.content_delta!r}",
                                        )
                                    elif isinstance(event.delta, ToolCallPartDelta):
                                        print(
                                            f"[Request] Part {event.index} args delta: {event.delta.args_delta}",
                                        )
                                elif isinstance(event, FinalResultEvent):
                                    print(
                                        f"[Result] The model started producing a final result (tool_name={event.tool_name})",
                                    )
                                    final_result_found = True
                                    break

                            if final_result_found:
                                # Once the final result is found, we can call `AgentStream.stream_text()` to stream the text.
                                # A similar `AgentStream.stream_output()` method is available to stream structured output.
                                print("[Output]")
                                async for output in request_stream.stream_text(delta=True):
                                    print(output, end="", flush=True)
                                print()
                    elif Agent.is_call_tools_node(node):
                        # A handle-response node => The model returned some data, potentially calls a tool
                        print("=== CallToolsNode: streaming partial response & tool usage ===")
                        async with node.stream(run.ctx) as handle_stream:
                            async for event in handle_stream:
                                if isinstance(event, FunctionToolCallEvent):
                                    print(
                                        f"[Tools] The LLM calls tool={event.part.tool_name!r} with args={event.part.args} (tool_call_id={event.part.tool_call_id!r})",
                                    )
                                elif isinstance(event, FunctionToolResultEvent):
                                    print(
                                        f"[Tools] Tool call {event.tool_call_id!r} returned => {event.result.content}",
                                    )
                    elif Agent.is_end_node(node):
                        # Once an End node is reached, the agent run is complete
                        assert run.result is not None
                        assert run.result.output == node.data.output
                        print(f"=== Final Agent Output: {run.result.output} ===")

            result = await agent.run(user_input)
            print(f"Agent: {result.output}\n")
        except Exception as e:
            print(f"Error running agent: {e}")

        user_input = input("User: ").strip()


if __name__ == "__main__":
    asyncio.run(main())
