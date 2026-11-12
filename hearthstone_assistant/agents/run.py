import inspect
import json
import time
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langsmith import tracing_context
from hearthstone_assistant.models.deepseek import collect_reply
from hearthstone_assistant.prompt.routing import system_for
from hearthstone_assistant.tools.cards.client import connect,definitions


class State(TypedDict):
    question: str
    answer: str
    messages: list[dict]
    requests: int
    seen_ids: list[str]


def route(state):
    return "tools" if state["messages"][-1].get("tool_calls") else END


def build_graph(settings,log,on_text,tools=None,on_step=None):
    async def model_node(state):
        step = state["requests"]+1
        if step>5: raise ValueError("模型请求次数达到5次上限")
        from hearthstone_assistant.memory.context import estimate
        schema = definitions()
        if estimate(state["messages"])+len(json.dumps(schema,ensure_ascii=False).encode())>24000:
            raise ValueError("当前工具上下文超过预算，本轮未提交")
        log.emit("graph_node_start",node="model",step=step)
        if on_step:
            notice = on_step(step)
            if inspect.isawaitable(notice): await notice
        reply = await collect_reply(settings,state["messages"],log,on_text,schema)
        calls = reply.get("tool_calls",[])
        ids = [call["id"] for call in calls]
        if len(calls)>3 or any(not i for i in ids) or len(ids)!=len(set(ids)) or set(ids).intersection(state["seen_ids"]):
            raise ValueError("工具数量或调用ID不合法")
        if calls and step==5: raise ValueError("模型请求预算用完，最后一批工具未执行")
        if not calls and "<｜｜DSML" in (reply["content"] or ""): raise ValueError("DSML文字不是工具调用")
        log.emit("graph_node_end",node="model",step=step)
        return {"messages":state["messages"]+[reply],"requests":step,
                "seen_ids":state["seen_ids"]+ids,"answer":reply["content"] or ""}

    async def tools_node(state):
        messages = []
        for call in state["messages"][-1]["tool_calls"]:
            function = call["function"]
            arguments = json.loads(function["arguments"])
            log.emit("tool_start",tool=function["name"],step=state["requests"])
            if hasattr(log,"detail"): log.detail("工具请求",call)
            started = time.perf_counter()
            result = await tools.execute(function["name"],arguments)
            log.emit("tool_end",tool=function["name"],seconds=round(time.perf_counter()-started,3),status="ok" if result.get("ok") else "error")
            if hasattr(log,"detail"): log.detail("工具返回",{"tool_call_id":call["id"],"result":result})
            messages.append({"role":"tool","tool_call_id":call["id"],"content":json.dumps(result,ensure_ascii=False,allow_nan=False)})
        return {"messages":state["messages"]+messages}

    graph = StateGraph(State)
    graph.add_node("model",model_node)
    graph.add_node("tools",tools_node)
    graph.add_edge(START,"model")
    graph.add_conditional_edges("model",route,{"tools":"tools",END:END})
    graph.add_edge("tools","model")
    return graph.compile()


async def run_agent(settings,question,log,on_text,messages=None,on_step=None,return_messages=False,fingerprint="auto"):
    if fingerprint=="auto":
        from hearthstone_assistant.tools.cards.catalog import snapshot
        fingerprint=snapshot(settings.project_root)["fingerprint"]
    initial = messages if messages is not None else [{"role":"system","content":system_for(question)},{"role":"user","content":question}]
    with tracing_context(enabled=False):
        async with connect(settings,log,fingerprint) as tools:
            result = await build_graph(settings,log,on_text,tools,on_step).ainvoke(
                {"question":question,"messages":initial,"requests":0,"seen_ids":[]},{"recursion_limit":13})
    current = result["messages"][len(initial)-1:]
    return (result["answer"],current) if return_messages else result["answer"]
