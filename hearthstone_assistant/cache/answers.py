import hashlib
import json
from hearthstone_assistant.tools.cards.catalog import snapshot


def request_key(settings, messages, card_snapshot="auto"):
    # 必须随提示/请求行为/数据能力变化更新版本；未来加工具还需schema与来源快照。
    root = getattr(settings, "project_root", None)
    fingerprint = snapshot(root)["fingerprint"] if card_snapshot=="auto" and root is not None else None if card_snapshot=="auto" else card_snapshot
    payload = {"cache_version": "cards-mcp-v2", "card_snapshot": fingerprint, "model": settings.model,
               "base_url": settings.base_url, "messages": messages,
               "max_tokens": 1024, "thinking": "disabled"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()
