"""每个操作在工作线程中创建/关闭SQLite连接，不跨线程共享连接。"""
import asyncio
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from hearthstone_assistant.storage.sqlite import SessionStore,transcript_json


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


class Records(SessionStore):
    def initialize_web(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS accounts(
          username TEXT PRIMARY KEY, user_id TEXT UNIQUE NOT NULL REFERENCES users(id),
          salt TEXT NOT NULL, password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS logins(
          token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS preferences(
          user_id TEXT NOT NULL REFERENCES users(id), key TEXT NOT NULL, value TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id,key));
        CREATE TABLE IF NOT EXISTS requests(
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, session_id TEXT NOT NULL,
          request_key TEXT NOT NULL, question_hash TEXT NOT NULL,
          status TEXT NOT NULL, turn_number INTEGER, run_id TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(user_id,session_id,request_key),
          FOREIGN KEY(user_id,session_id) REFERENCES sessions(user_id,id));
        """)
        # 当前服务约定单worker；重启不自动重做收费请求。
        with self.db:
            self.db.execute("UPDATE requests SET status='interrupted' WHERE status='running'")

    def register(self, username, password):
        user, salt = uuid.uuid4().hex, secrets.token_hex(16)
        hashed = password_hash(password, salt)
        try:
            with self.db:
                self.db.execute("INSERT INTO users(id) VALUES(?)", (user,))
                self.db.execute("INSERT INTO accounts VALUES(?,?,?,?)", (username, user, salt, hashed))
        except sqlite3.IntegrityError:
            raise ValueError("用户名已存在") from None
        return {"id": user, "username": username}

    def login(self, username, password):
        row = self.db.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
        actual = password_hash(password, row["salt"] if row else "00"*16)
        if row is None or not hmac.compare_digest(actual, row["password_hash"]):
            return None
        return {"id": row["user_id"], "username": row["username"]}

    def issue_login(self, user):
        token = secrets.token_urlsafe(32)
        with self.db:
            self.db.execute("DELETE FROM logins WHERE expires_at<=?", (time.time(),))
            self.db.execute("INSERT INTO logins VALUES(?,?,?)", (digest(token), user, time.time()+86400))
        return token

    def authenticate(self, token):
        row = self.db.execute("SELECT a.user_id AS id,a.username FROM logins l JOIN accounts a ON a.user_id=l.user_id WHERE l.token_hash=? AND l.expires_at>?", (digest(token), time.time())).fetchone()
        return dict(row) if row else None

    def logout(self, token):
        with self.db:
            self.db.execute("DELETE FROM logins WHERE token_hash=?", (digest(token),))

    def session_list(self, user):
        return [dict(r) for r in self.db.execute("""SELECT s.id,s.created_at,
          (SELECT question FROM turns t WHERE t.user_id=s.user_id AND t.session_id=s.id ORDER BY number LIMIT 1) AS title,
          (SELECT COUNT(*) FROM turns t WHERE t.user_id=s.user_id AND t.session_id=s.id) AS turn_count
          FROM sessions s WHERE s.user_id=? ORDER BY s.created_at DESC,s.rowid DESC LIMIT 100""", (user,))]

    def get_preferences(self, user):
        return {r["key"]: r["value"] for r in self.db.execute("SELECT key,value FROM preferences WHERE user_id=?", (user,))}

    def put_preferences(self, user, values):
        with self.db:
            self.db.execute("DELETE FROM preferences WHERE user_id=?", (user,))
            self.db.executemany("INSERT INTO preferences(user_id,key,value) VALUES(?,?,?)",
                                [(user, k, v.strip()) for k,v in values.items() if v.strip()])

    def begin_request(self, user, session, key, question_hash, turn_id, run_id):
        self.require(user, session)
        with self.db:
            old = self.db.execute("SELECT * FROM requests WHERE user_id=? AND session_id=? AND request_key=?", (user, session, key)).fetchone()
            if old:
                if old["question_hash"] != question_hash:
                    raise ValueError("同一请求编号不能用于不同内容")
                return dict(old)
            self.db.execute("INSERT INTO requests(id,user_id,session_id,request_key,question_hash,status,run_id) VALUES(?,?,?,?,?,'running',?)",
                            (turn_id,user,session,key,question_hash,run_id))
        return None

    def request_status(self, user, session, turn_id):
        self.require(user, session)
        row = self.db.execute("SELECT id,status,turn_number,run_id FROM requests WHERE user_id=? AND session_id=? AND id=?", (user,session,turn_id)).fetchone()
        if not row:
            raise ValueError("任务不存在")
        result = dict(row)
        if row["status"] == "completed":
            answer = self.db.execute("SELECT answer FROM turns WHERE user_id=? AND session_id=? AND number=?", (user,session,row["turn_number"])).fetchone()
            result["answer"] = answer["answer"] if answer else None
        return result

    def complete_request(self, user, session, turn_id, question, answer, expected_count, messages=None):
        # 完整轮次和任务终态在同一SQLite事务内提交。
        self.require(user, session)
        payload=transcript_json(question,answer,messages)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            count = self.db.execute("SELECT COUNT(*) FROM turns WHERE user_id=? AND session_id=?", (user,session)).fetchone()[0]
            status = self.db.execute("SELECT status FROM requests WHERE id=? AND user_id=? AND session_id=?", (turn_id,user,session)).fetchone()
            if count != expected_count or not status or status["status"] != "running":
                raise ValueError("任务状态或会话版本冲突")
            self.db.execute("INSERT INTO turns(user_id,session_id,number,question,answer,messages_json) VALUES(?,?,?,?,?,?)", (user,session,count+1,question,answer,payload))
            self.db.execute("UPDATE requests SET status='completed',turn_number=? WHERE id=? AND user_id=? AND session_id=?", (count+1,turn_id,user,session))

    def fail_request(self, user, session, turn_id, status):
        with self.db:
            self.db.execute("UPDATE requests SET status=? WHERE id=? AND user_id=? AND session_id=? AND status='running'", (status,turn_id,user,session))


class Repository:
    def __init__(self, root):
        self.path = root / "data" / "assistant.sqlite3"

    async def call(self, method, *args):
        def invoke():
            store = Records(self.path)
            try:
                return getattr(store, method)(*args)
            finally:
                store.close()
        return await asyncio.to_thread(invoke)

    async def summary(self, *args):
        return await self.call("summary", *args)

    async def save_summary(self, *args):
        return await self.call("save_summary", *args)
