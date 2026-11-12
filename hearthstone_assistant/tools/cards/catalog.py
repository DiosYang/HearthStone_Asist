import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata

SOURCE_URL = "https://api.hearthstonejson.com/v1/latest/zhCN/cards.collectible.json"
MAX_BYTES = 16 * 1024 * 1024


def directory(root):
    return Path(root) / "data" / "cards" / "zhCN"


def snapshot(root):
    try:
        data = json.loads((directory(root)/"manifest.json").read_text(encoding="utf-8"))
        fingerprint = data["fingerprint"]
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint) or data["source_url"] != SOURCE_URL:
            raise ValueError("无效卡库清单")
        if not (directory(root)/(fingerprint+".json")).is_file():
            raise ValueError("卡库文件缺失")
        return {k: data.get(k) for k in ("fingerprint", "source_url", "retrieved_at", "last_modified", "etag", "locale", "build")}
    except (OSError, ValueError, KeyError, TypeError):
        return {"fingerprint": None, "status": "not_ready"}


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "br": self.parts.append("\n")


def readable(text):
    parser = PlainText()
    parser.feed(text or "")
    value = unescape("".join(parser.parts)).replace("[x]", "")
    return re.sub(r"[$#](?=\d)", "", value).strip()


def normalized(value):
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


class CardCatalog:
    def __init__(self, root, fingerprint=None):
        self.source = snapshot(root)
        if not self.source.get("fingerprint"):
            raise ValueError("card_data_not_ready：请先运行卡库更新命令")
        if fingerprint and self.source["fingerprint"] != fingerprint:
            # 按父任务选中的不可变快照读取，不在一次任务中偷偷换版本。
            self.source = {**self.source, "fingerprint": fingerprint, "retrieved_at": None,
                           "last_modified": None, "etag": None}
        chosen = self.source["fingerprint"]
        if not re.fullmatch(r"[0-9a-f]{64}", chosen):
            raise ValueError("无效快照")
        path = directory(root)/(chosen+".json")
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("卡库超出大小限制")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != chosen:
            raise ValueError("卡库指纹不匹配，请重新更新")
        cards = json.loads(raw)
        if not isinstance(cards, list) or any(not isinstance(c, dict) or not isinstance(c.get("id"), str) or not isinstance(c.get("name"), str) for c in cards):
            raise ValueError("卡库数据结构无效")
        self.by_id = {card["id"]: card for card in cards}
        if len(self.by_id) != len(cards):
            raise ValueError("卡库存在重复ID")
        self.cards = cards

    def public_card(self, card, detail=False):
        fields = ("id", "dbfId", "name", "cost", "type", "cardClass", "classes", "set", "rarity", "collectible")
        value = {field: card[field] for field in fields if field in card}
        if detail:
            value.update({field: card[field] for field in ("attack", "health", "durability", "races", "mechanics", "spellSchool") if field in card})
            value["text"] = readable(card.get("text", ""))
            value["raw_text"] = card.get("text", "")
            value["standard_legal"] = None
        return value

    def search(self, query, limit=5):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 80 or type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError("查询长度1—80，limit为1—5整数")
        term = normalized(query)
        exact = [c for c in self.cards if normalized(c["name"]) == term or c["id"].casefold() == query.casefold().strip() or str(c.get("dbfId")) == query.strip()]
        matches = exact or [c for c in self.cards if term in normalized(c["name"])]
        matches.sort(key=lambda c: c["id"])
        return {"ok": True, "status": "not_found" if not matches else "ambiguous" if len(matches)>1 else "found",
                "match_type": "exact" if exact else "contains", "total": len(matches), "truncated": len(matches)>limit,
                "cards": [self.public_card(c) for c in matches[:limit]], "source": self.source,
                "notice": "同名卡不可自动认定同一实体；本快照不提供当前标准合法性或胜率。"}

    def get(self, card_id):
        card = self.by_id.get(card_id)
        return {"ok": True, "status": "found" if card else "not_found",
                "card": self.public_card(card, detail=True) if card else None, "source": self.source,
                "notice": "卡面数据快照，不是实时游戏判定器；未确认标准合法性、热修或天梯胜率。"}
