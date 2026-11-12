"""真实MCP查询验证，不请求DeepSeek。"""
import asyncio
import json
from types import SimpleNamespace
from hearthstone_assistant.config import PROJECT_ROOT
from hearthstone_assistant.log import EventLog
from hearthstone_assistant.tools.cards.catalog import snapshot
from hearthstone_assistant.tools.cards.client import connect


async def main():
    log=EventLog(PROJECT_ROOT/"data/logs",console=True)
    settings=SimpleNamespace(project_root=PROJECT_ROOT)
    async with connect(settings,log,snapshot(PROJECT_ROOT)["fingerprint"]) as tools:
        found=await tools.execute("search_cards",{"query":"火球术","limit":5})
        print(json.dumps(found,ensure_ascii=False,indent=2))
        if found.get("cards"):
            card=await tools.execute("get_card",{"card_id":found["cards"][0]["id"]})
            print("以下仅验证指定候选ID的读取，不代表自动选中了标准版本：")
            print(json.dumps(card,ensure_ascii=False,indent=2))


if __name__=="__main__": asyncio.run(main())
