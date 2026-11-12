import re
import sqlite3
import uuid
import time


class SessionStore:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS sessions(
            user_id TEXT NOT NULL REFERENCES users(id), id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id,id));
        CREATE TABLE IF NOT EXISTS turns(
            user_id TEXT NOT NULL, session_id TEXT NOT NULL, number INTEGER NOT NULL,
            question TEXT NOT NULL, answer TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id,session_id,number),
            FOREIGN KEY(user_id,session_id) REFERENCES sessions(user_id,id));
        CREATE TABLE IF NOT EXISTS summaries(
            user_id TEXT NOT NULL, session_id TEXT NOT NULL,
            through_turn INTEGER NOT NULL, text TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id,session_id),
            FOREIGN KEY(user_id,session_id) REFERENCES sessions(user_id,id));
        CREATE TABLE IF NOT EXISTS answer_cache(
            user_id TEXT NOT NULL, session_id TEXT NOT NULL, cache_key TEXT NOT NULL,
            answer TEXT NOT NULL, expires_at REAL NOT NULL,
            PRIMARY KEY(user_id,session_id,cache_key),
            FOREIGN KEY(user_id,session_id) REFERENCES sessions(user_id,id));
        """)

    def ensure_user(self, user):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user):
            raise ValueError("用户标识限1—64位字母、数字、下划线或短横线")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO users(id) VALUES(?)", (user,))

    def create(self, user):
        self.ensure_user(user)
        session = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO sessions(user_id,id) VALUES(?,?)", (user, session))
        return session

    def require(self, user, session):
        if not self.db.execute("SELECT 1 FROM sessions WHERE user_id=? AND id=?", (user, session)).fetchone():
            raise ValueError("会话不存在或不属于当前用户")

    def list(self, user):
        return [dict(r) for r in self.db.execute(
            "SELECT id,created_at FROM sessions WHERE user_id=? ORDER BY created_at,id", (user,))]

    def turns(self, user, session):
        self.require(user, session)
        return [dict(r) for r in self.db.execute(
            "SELECT number,question,answer FROM turns WHERE user_id=? AND session_id=? ORDER BY number", (user, session))]

    def append(self, user, session, question, answer, expected_count):
        self.require(user, session)
        # 乐观并发检查：不把基于旧上下文生成的回复追加到已变化会话。
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            count = self.db.execute("SELECT COUNT(*) FROM turns WHERE user_id=? AND session_id=?", (user, session)).fetchone()[0]
            if count != expected_count:
                raise ValueError("会话已被另一进程更新，本次回复未提交")
            self.db.execute("INSERT INTO turns VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)",
                            (user, session, count+1, question, answer))

    def summary(self, user, session):
        self.require(user, session)
        row = self.db.execute("SELECT through_turn,text FROM summaries WHERE user_id=? AND session_id=?", (user, session)).fetchone()
        return dict(row) if row else {"through_turn": 0, "text": ""}

    def save_summary(self, user, session, text, through, expected_through):
        self.require(user, session)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.summary(user, session)
            count = self.db.execute("SELECT COUNT(*) FROM turns WHERE user_id=? AND session_id=?", (user, session)).fetchone()[0]
            if old["through_turn"] != expected_through or not expected_through < through <= count:
                raise ValueError("摘要版本冲突，未覆盖已有摘要")
            self.db.execute("INSERT INTO summaries VALUES(?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id,session_id) DO UPDATE SET through_turn=excluded.through_turn,text=excluded.text,updated_at=CURRENT_TIMESTAMP",
                            (user, session, through, text))

    def close(self):
        self.db.close()

    def cached_answer(self, user, session, key):
        self.require(user, session)
        row = self.db.execute("SELECT answer FROM answer_cache WHERE user_id=? AND session_id=? AND cache_key=? AND expires_at>?",
                              (user, session, key, time.time())).fetchone()
        return row["answer"] if row else None

    def cache_answer(self, user, session, key, answer, ttl=900):
        self.require(user, session)
        with self.db:
            self.db.execute("DELETE FROM answer_cache WHERE user_id=? AND session_id=? AND expires_at<=?",
                            (user, session, time.time()))
            self.db.execute("INSERT INTO answer_cache VALUES(?,?,?,?,?) ON CONFLICT(user_id,session_id,cache_key) DO UPDATE SET answer=excluded.answer,expires_at=excluded.expires_at",
                            (user, session, key, answer, time.time()+ttl))
