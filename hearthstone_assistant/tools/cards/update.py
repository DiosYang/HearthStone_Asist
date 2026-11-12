"""固定公开URL下载卡库，不调用模型。不可变快照+原子清单切换。"""
from datetime import datetime, timezone
import hashlib
import json
import os
import tempfile
import httpx
from hearthstone_assistant.config import PROJECT_ROOT
from hearthstone_assistant.tools.cards.catalog import SOURCE_URL, MAX_BYTES, directory


def atomic_write(path, data):
    fd, name = tempfile.mkstemp(prefix=".cards-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def update(root=PROJECT_ROOT):
    target = directory(root)
    target.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=httpx.Timeout(45, connect=10), follow_redirects=False) as client:
        with client.stream("GET", SOURCE_URL, headers={"Accept":"application/json"}) as response:
            response.raise_for_status()
            # 不跟随未知重定向，避免未来配置变化导致任意站点请求。
            if response.status_code != 200:
                raise ValueError("卡库下载未返回200，保留旧快照")
            raw = bytearray()
            for part in response.iter_bytes():
                raw.extend(part)
                if len(raw) > MAX_BYTES: raise ValueError("卡库响应过大，保留旧快照")
            headers = response.headers
    cards = json.loads(raw)
    if not isinstance(cards, list) or not cards or any(not isinstance(c,dict) or not isinstance(c.get("id"),str) or not isinstance(c.get("name"),str) for c in cards):
        raise ValueError("卡库结构无效，保留旧快照")
    if len({c["id"] for c in cards}) != len(cards): raise ValueError("重复卡牌ID，保留旧快照")
    fingerprint = hashlib.sha256(raw).hexdigest()
    manifest = {"fingerprint":fingerprint,"source_url":SOURCE_URL,"locale":"zhCN","build":None,
                "retrieved_at":datetime.now(timezone.utc).isoformat(),"etag":headers.get("etag"),
                "last_modified":headers.get("last-modified"),"card_count":len(cards)}
    atomic_write(target/(fingerprint+".json"), raw)
    atomic_write(target/"manifest.json", json.dumps(manifest,ensure_ascii=False,indent=2).encode())
    return manifest


if __name__ == "__main__":
    try:
        print(json.dumps(update(), ensure_ascii=False, indent=2))
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise SystemExit("卡库更新失败，原快照未清空："+type(exc).__name__) from None
