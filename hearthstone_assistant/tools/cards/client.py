import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import json
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, ConfigDict, Field
from hearthstone_assistant.config import PROJECT_ROOT


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1,max_length=80)
    limit: int = Field(default=5,ge=1,le=5)


class GetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    card_id: str = Field(min_length=1,max_length=100)


TOOLS = {"search_cards": (SearchInput,"搜索中文卡名、唯一卡牌ID或dbfId；同名返回候选，不能默选第一条。"),
         "get_card": (GetInput,"按精确card_id读取卡牌费用、效果、属性与快照来源。不要凭空编ID；不返回当前标准合法性或胜率。")}


def definitions():
    return [{"type":"function","function":{"name":name,"description":description,"parameters":model.model_json_schema()}}
            for name,(model,description) in TOOLS.items()]


class CardTools:
    def __init__(self, session): self.session = session

    async def execute(self, name, arguments):
        if name not in TOOLS: return {"ok":False,"error":{"type":"unknown_tool"}}
        try:
            values = TOOLS[name][0].model_validate(arguments).model_dump()
        except ValueError:
            return {"ok":False,"error":{"type":"invalid_arguments","message":"参数未通过工具Schema校验"}}
        result = await self.session.call_tool(name,values)
        text = "\n".join(part.text for part in result.content if part.type == "text")
        if len(text.encode()) > 18000: return {"ok":False,"error":{"type":"tool_output_too_large"}}
        if result.isError:
            return {"ok":False,"error":{"type":"mcp_tool_error","message":text[:600]}}
        try: return json.loads(text)
        except ValueError: return {"ok":False,"error":{"type":"invalid_tool_result"}}


def leaves(error):
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in leaves(child)]
    return [error]


@asynccontextmanager
async def connect(settings, log, fingerprint=None):
    env = {"HEARTH_CARD_ROOT":str(settings.project_root),"PYTHONUTF8":"1"}
    env["HEARTH_CARD_SNAPSHOT"] = fingerprint or "missing"
    params = StdioServerParameters(command=sys.executable,args=["-m","hearthstone_assistant.tools.cards.server"],
                                   cwd=str(PROJECT_ROOT),env=env)
    try:
        async with stdio_client(params) as (reader,writer):
            async with ClientSession(reader,writer,read_timeout_seconds=timedelta(seconds=15)) as session:
                await session.initialize()
                catalog = await session.list_tools()
                names = {item.name for item in catalog.tools}
                if not set(TOOLS).issubset(names): raise ValueError("卡牌MCP未提供约定工具")
                log.emit("mcp_connected",status="cards_readonly")
                yield CardTools(session)
    except BaseException as exc:
        # 保留真正的模型/网络异常类型，不把yield作用域内所有错误错标为MCP错误。
        actual = leaves(exc)
        if len(actual) == 1 and actual[0] is not exc: raise actual[0] from exc
        raise
    finally:
        log.emit("mcp_closed")
