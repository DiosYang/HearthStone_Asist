import hashlib
import json


def request_key(settings, messages):
    # 必须随提示/请求行为/数据能力变化更新版本；未来加工具还需schema与来源快照。
    payload = {"cache_version": "text-only-v1", "model": settings.model,
               "base_url": settings.base_url, "messages": messages,
               "max_tokens": 1024, "thinking": "disabled"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()
