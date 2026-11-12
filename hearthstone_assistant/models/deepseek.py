"""真实LangChain流：摘要只读文字，Agent收集完整工具参数后才执行。"""
from contextlib import aclosing
import inspect
import json
import time
import httpx
from langchain_deepseek import ChatDeepSeek
from langsmith import tracing_context


def text_piece(chunk):
    if chunk.tool_call_chunks: raise ValueError("纯文本请求不接受工具调用")
    if not isinstance(chunk.content,str): raise ValueError("本阶段只接受文本片段")
    return chunk.content


def message_from_chunk(chunk):
    if not isinstance(chunk.content,str): raise ValueError("只支持文本内容")
    if chunk.invalid_tool_calls: raise ValueError("工具参数不是完整合法JSON")
    message = {"role":"assistant","content":chunk.content or None}
    if chunk.tool_call_chunks:
        calls=[]
        for part in chunk.tool_call_chunks:
            try:
                args=json.loads(part["args"])
            except (ValueError,TypeError): raise ValueError("工具参数分片尚未形成完整JSON") from None
            if not isinstance(args,dict): raise ValueError("工具参数必须是对象")
            calls.append({"id":part["id"],"type":"function","function":{
                "name":part["name"],"arguments":json.dumps(args,ensure_ascii=False,allow_nan=False)}})
        message["tool_calls"]=calls
    return message


async def chunks(settings,messages,log,stage="chat",tools=None):
    started = time.perf_counter()
    finish,usage,aggregate = None,None,None
    completed,printed = False,False
    error_type = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(60,connect=10)) as asynchronous:
        with httpx.Client(timeout=60) as synchronous:
            model = ChatDeepSeek(model=settings.model,api_key=settings.api_key,base_url=settings.base_url,
                max_retries=0,max_tokens=1024,http_async_client=asynchronous,http_client=synchronous,
                stream_usage=True,extra_body={"thinking":{"type":"disabled"}})
            runnable = model.bind_tools(tools,tool_choice="auto") if tools else model
            log.emit("model_request",model=settings.model,stage=stage)
            if hasattr(log,"detail"):
                log.detail("请求（应用层，不包含认证头）",{"model":settings.model,"messages":messages,
                    "tools":tools or [],"stream":True,"max_tokens":1024,"thinking":{"type":"disabled"},"stage":stage})
            try:
                with tracing_context(enabled=False):
                    async with aclosing(runnable.astream(messages)) as stream:
                        async for chunk in stream:
                            if not isinstance(chunk.content,str): raise ValueError("只支持文本流")
                            aggregate = chunk if aggregate is None else aggregate + chunk
                            finish = chunk.response_metadata.get("finish_reason") or finish
                            if chunk.usage_metadata is not None: usage = chunk.usage_metadata
                            if chunk.content and not printed:
                                log.emit("first_text",stage=stage,seconds=round(time.perf_counter()-started,3))
                                printed=True
                            yield chunk
                if aggregate is None: raise ValueError("响应为空")
                message = message_from_chunk(aggregate)
                if finish not in ("stop","tool_calls") or (finish=="tool_calls" and (not tools or not message.get("tool_calls"))) or (finish=="stop" and (message.get("tool_calls") or not (message["content"] or "").strip())):
                    raise ValueError("响应不完整，可能输出达到上限或连接提前结束")
                completed = True
            except BaseException as exc:
                error_type = type(exc).__name__
                raise
            finally:
                fields = {"seconds":round(time.perf_counter()-started,3),"finish_reason":finish,
                          "status":"finished" if completed else "incomplete"}
                if usage is not None:
                    fields.update(prompt_tokens=usage["input_tokens"],completion_tokens=usage["output_tokens"],total_tokens=usage["total_tokens"])
                log.emit("model_stream_end",stage=stage,**fields)
                if hasattr(log,"detail"):
                    try: reply = message_from_chunk(aggregate) if aggregate is not None else None
                    except ValueError: reply = {"content":getattr(aggregate,"content",None),"invalid_tool_arguments":True}
                    log.detail("返回（LangChain归一化；不是原始HTTP响应）",{"langchain_message_id":getattr(aggregate,"id",None),"message":reply,
                               "finish_reason":finish,"usage":usage,"complete":completed,"error_type":error_type,"stage":stage})


async def stream_reply(settings,messages,log,stage="chat"):
    async with aclosing(chunks(settings,messages,log,stage)) as stream:
        async for chunk in stream:
            text = text_piece(chunk)
            if text: yield text


async def collect_reply(settings,messages,log,on_text,tools):
    aggregate = None
    async with aclosing(chunks(settings,messages,log,tools=tools)) as stream:
        async for chunk in stream:
            aggregate = chunk if aggregate is None else aggregate + chunk
            if chunk.content:
                result = on_text(chunk.content)
                if inspect.isawaitable(result): await result
    return message_from_chunk(aggregate)
