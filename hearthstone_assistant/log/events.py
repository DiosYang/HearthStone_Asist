"""单进程教学版JSONL；仅允许已定义的元数据字段，不接收完整请求。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

ALLOWED_FIELDS = {"model", "key_configured", "step", "tool", "status", "error_type",
                  "seconds", "prompt_tokens", "completion_tokens", "total_tokens", "finish_reason", "node",
                  "stage", "estimate_units", "budget", "summary_used", "summary_through"}


class EventLog:
    def __init__(self, directory, console=True):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.run_id = uuid.uuid4().hex
        self.path = directory / (self.run_id + ".jsonl")
        self.sequence = 0
        self.console = console
        self.user_id = None
        self.session_id = None

    def emit(self, event, **fields):
        unknown = set(fields) - ALLOWED_FIELDS
        if unknown:
            raise ValueError("日志字段不在允许列表；不能传Key、请求头或完整正文")
        self.sequence += 1
        record = {"time": datetime.now(timezone.utc).isoformat(), "run_id": self.run_id,
                  "sequence": self.sequence, "event": event,
                  "user_id": self.user_id, "session_id": self.session_id, **fields}
        line = json.dumps(record, ensure_ascii=False, allow_nan=False)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
        if self.console:
            print(f"[{self.sequence:03d}] {event} " + json.dumps(fields, ensure_ascii=False))
