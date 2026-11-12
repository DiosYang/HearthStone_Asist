"""本机只读卡牌MCP；stdin/stdout仅承载协议，不接模型Key。"""
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from hearthstone_assistant.tools.cards.catalog import CardCatalog

server = FastMCP("hearthside-cards")
catalog = None


def load():
    global catalog
    if catalog is None:
        if os.getenv("HEARTH_CARD_SNAPSHOT")=="missing": raise ValueError("card_data_not_ready：本轮未选择卡库快照，请先更新卡库")
        catalog = CardCatalog(Path(os.environ["HEARTH_CARD_ROOT"]), os.getenv("HEARTH_CARD_SNAPSHOT") or None)
    return catalog


@server.tool()
def search_cards(query: str, limit: int = 5) -> dict:
    """搜索中文可收藏卡牌名称、卡牌ID或dbfId，最多5条；同名返回候选，不猜标准合法性。"""
    return load().search(query, limit)


@server.tool()
def get_card(card_id: str) -> dict:
    """按search_cards返回的精确id读取卡牌效果/费用/属性与快照来源；不允许传URL或路径。"""
    if not 1 <= len(card_id) <= 100: raise ValueError("card_id长度无效")
    return load().get(card_id)


if __name__ == "__main__":
    server.run(transport="stdio")
