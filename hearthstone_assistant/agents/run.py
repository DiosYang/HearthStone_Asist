from contextlib import aclosing
import inspect
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langsmith import tracing_context
from hearthstone_assistant.models.deepseek import stream_reply
from hearthstone_assistant.prompt import SYSTEM_PROMPT


class State(TypedDict):
    question: str
    answer: str
    messages: list[dict]


def build_graph(settings, log, on_text):
    async def model_node(state):
        log.emit("graph_node_start", node="model")
        parts = []
        messages = state["messages"]
        async with aclosing(stream_reply(settings, messages, log)) as stream:
            async for text in stream:
                parts.append(text)
                delivered = on_text(text)
                if inspect.isawaitable(delivered):
                    await delivered
        log.emit("graph_node_end", node="model")
        return {"answer": "".join(parts)}

    graph = StateGraph(State)
    graph.add_node("model", model_node)
    graph.add_edge(START, "model")
    graph.add_edge("model", END)
    return graph.compile()  # 暂无checkpointer，不宣称自动恢复。


async def run_agent(settings, question, log, on_text, messages=None):
    with tracing_context(enabled=False):
        result = await build_graph(settings, log, on_text).ainvoke(
            {"question": question, "messages": messages if messages is not None else [
                {"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]},
            {"recursion_limit": 4})
    return result["answer"]
