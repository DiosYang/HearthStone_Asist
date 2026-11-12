"""每用户/会话可读文本日志；结构化事件仍保留每轮JSONL。"""
from datetime import datetime, timezone
import json
import re
from hearthstone_assistant.log.events import EventLog

SENSITIVE = {"api_key", "authorization", "password", "cookie", "headers", "token", "access_token", "refresh_token"}


def session_directory(root, user, session):
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) for value in (user,session)):
        raise ValueError("日志用户/会话标识不合法")
    return root / user / session


def redact(value, secrets=()):
    if isinstance(value,dict):
        return {key:"[已隐藏]" if str(key).lower() in SENSITIVE else redact(item,secrets) for key,item in value.items()}
    if isinstance(value,(list,tuple)): return [redact(item,secrets) for item in value]
    if isinstance(value,str):
        for secret in secrets:
            if secret: value = value.replace(secret,"[已隐藏]")
        value = re.sub(r"\bBearer\s+[^\s\"']+", "Bearer [已隐藏]", value, flags=re.I)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[已隐藏]", value)
    return value


class SessionLog(EventLog):
    def __init__(self,root,user,session,turn_id,secrets=()):
        self.directory = session_directory(root,user,session)
        super().__init__(self.directory,console=False)
        self.user_id,self.session_id,self.turn_id = user,session,turn_id
        self.text_path = self.directory / "log.txt"
        self.secrets = tuple(s for s in secrets if s)

    def detail(self,title,value):
        body = json.dumps(redact(value,self.secrets),ensure_ascii=False,indent=2,allow_nan=False)
        if len(body)>200000: body=body[:200000]+"\n[日志正文过大，已截断]"
        block = (f"\n{'='*64}\n时间：{datetime.now(timezone.utc).isoformat()}\n"
                 f"用户：{self.user_id}\n会话：{self.session_id}\n轮次：{self.turn_id}\n运行：{self.run_id}\n"
                 f"--- {title} ---\n{body}\n")
        with self.text_path.open("a",encoding="utf-8") as stream: stream.write(block)

    def emit(self,event,**fields):
        cleaned=redact(fields,self.secrets)
        super().emit(event,**cleaned)
        self.detail(f"事件 [{self.sequence:03d}] {event}",cleaned)
