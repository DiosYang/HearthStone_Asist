"""单次真实文本流；不自动重试，不执行工具，不保存对话。"""
from contextlib import aclosing
import time
import httpx
from langchain_deepseek import ChatDeepSeek
from langsmith import tracing_context


def text_piece(chunk):
    if chunk.tool_call_chunks:
        raise ValueError("本阶段不接受工具调用")
    if not isinstance(chunk.content, str):
        raise ValueError("本阶段只接受文本片段")
    return chunk.content


async def stream_reply(settings, messages, log, stage="chat"):
    started = time.perf_counter()
    finish = None
    has_text = False
    usage = None
    completed = False
    # 凭据只交给允许的模型服务；不传给工具，不写日志。
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10)) as asynchronous:
        with httpx.Client(timeout=60) as synchronous:
            model = ChatDeepSeek(model=settings.model, api_key=settings.api_key,
                base_url=settings.base_url, max_retries=0, max_tokens=1024,
                http_async_client=asynchronous, http_client=synchronous, stream_usage=True,
                extra_body={"thinking": {"type": "disabled"}})
            log.emit("model_request", model=settings.model, stage=stage)
            try:
                with tracing_context(enabled=False):
                    async with aclosing(model.astream(messages)) as stream:
                        async for chunk in stream:
                            finish = chunk.response_metadata.get("finish_reason") or finish
                            if chunk.usage_metadata is not None:
                                usage = chunk.usage_metadata
                            piece = text_piece(chunk)
                            if piece:
                                if not has_text:
                                    log.emit("first_text", stage=stage, seconds=round(time.perf_counter()-started, 3))
                                    has_text = True
                                yield piece
                if finish != "stop" or not has_text:
                    raise ValueError("响应不完整，可能输出达到上限或连接提前结束")
                completed = True
            finally:
                # 有些服务失败/取消时不给usage，未知不记成0。
                fields = {"seconds": round(time.perf_counter()-started, 3),
                          "finish_reason": finish, "status": "finished" if completed else "incomplete"}
                if usage is not None:
                    fields.update(prompt_tokens=usage["input_tokens"],
                                  completion_tokens=usage["output_tokens"], total_tokens=usage["total_tokens"])
                log.emit("model_stream_end", stage=stage, **fields)
