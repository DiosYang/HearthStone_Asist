"""真实HTTP应用+临时SQLite；缓存夹具验证不调用模型，不伪造模型响应。"""
import json
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from hearthstone_assistant.config import Settings
from hearthstone_assistant.server.app import create_app
from hearthstone_assistant.server.repository import Records
from hearthstone_assistant.server.repository import Repository
from hearthstone_assistant.server.service import WebLog, execute_turn
from hearthstone_assistant.memory.context import compose
from hearthstone_assistant.cache.answers import request_key


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.settings = Settings("offline-only-not-real-key", "deepseek-flash", "https://api.deepseek.com", self.root, self.root/".env")
        self.client = TestClient(create_app(self.root, self.settings))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temporary.cleanup()

    def account(self, name="alice"):
        response = self.client.post("/api/auth/register", json={"username":name,"password":"study-password-123"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        return response.json()["user"]

    def test_auth_password_cookie_and_logout(self):
        self.assertEqual(self.client.get("/api/sessions").status_code, 401)
        user = self.account()
        store = Records(self.root/"data/assistant.sqlite3")
        row = store.db.execute("SELECT password_hash FROM accounts").fetchone()
        self.assertNotEqual(row[0], "study-password-123")
        self.assertEqual(store.db.execute("SELECT token_hash FROM logins").fetchone()[0].__len__(), 64)
        store.close()
        self.assertNotIn(self.settings.api_key, self.client.get("/api/auth/me").text)
        self.client.post("/api/auth/logout", json={})
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        wrong = self.client.post("/api/auth/login", json={"username":"alice","password":"wrong-password-123"})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"username":"alice","password":"study-password-123"}).status_code, 200)

    def test_isolation_preferences_origin_and_legacy_user(self):
        # 旧CLI用户ID不是网页登录名，不能靠同名注册接管旧会话。
        store = Records(self.root/"data/assistant.sqlite3")
        legacy = store.create("alice")
        store.close()
        user = self.account()
        self.assertNotEqual(user["id"], "alice")
        self.assertEqual(self.client.get(f"/api/sessions/{legacy}/messages").status_code, 404)
        session = self.client.post("/api/sessions", json={}).json()["id"]
        self.client.put("/api/preferences", json={"favorite_class":"法师"})
        self.assertEqual(self.client.get("/api/preferences").json()["preferences"], {"favorite_class":"法师"})
        denied = self.client.post("/api/sessions", json={}, headers={"Origin":"https://evil.invalid"})
        self.assertEqual(denied.status_code, 403)
        self.client.post("/api/auth/logout", json={})
        self.account("bob")
        self.assertEqual(self.client.get("/api/sessions").json()["sessions"], [])
        self.assertEqual(self.client.get("/api/preferences").json()["preferences"], {})
        self.assertEqual(self.client.get(f"/api/sessions/{session}/messages").status_code, 404)
        self.assertEqual(self.client.post(f"/api/sessions/{session}/turns", json={"question":"q","request_id":"a"*32}).status_code, 404)

    def test_real_cache_sse_persistence_idempotency_and_logs(self):
        user = self.account()
        session = self.client.post("/api/sessions", json={}).json()["id"]
        question = "缓存组件验收"
        store = Records(self.root/"data/assistant.sqlite3")
        key = request_key(self.settings, compose([],question,{"through_turn":0,"text":""}))
        store.cache_answer(user["id"],session,key,"这是显式缓存夹具，不是模型回答。")
        store.close()
        body = {"question":question,"request_id":"a"*32}
        # 仅加禁止联网护栏，不提供任何模拟模型输出。
        with patch("hearthstone_assistant.agents.run.collect_reply", side_effect=AssertionError("不允许模型请求")):
            response = self.client.post(f"/api/sessions/{session}/turns", json=body)
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertTrue(any(e["type"] == "cache" and e["hit"] for e in events), events)
        self.assertEqual(events[-1]["type"], "turn_completed", events)
        turn_id = events[0]["turn_id"]
        history = self.client.get(f"/api/sessions/{session}/messages").json()["turns"]
        self.assertEqual(len(history), 1)
        repeated = self.client.post(f"/api/sessions/{session}/turns", json=body)
        self.assertIn('"replayed": true', repeated.text)
        self.assertEqual(len(self.client.get(f"/api/sessions/{session}/messages").json()["turns"]), 1)
        self.assertEqual(self.client.post(f"/api/sessions/{session}/turns", json={**body,"question":"改了"}).status_code, 409)
        self.assertEqual(self.client.post(f"/api/sessions/{session}/turns/{turn_id}/cancel",json={}).json()["status"], "completed")
        logs = self.client.get(f"/api/sessions/{session}/turns/{turn_id}/events").json()["events"]
        self.assertTrue(any(e["event"]=="session_saved" for e in logs))
        self.assertNotIn("offline-only", json.dumps(logs))
        text_log=self.client.get(f"/api/sessions/{session}/log")
        self.assertEqual(text_log.status_code,200)
        self.assertIn("用户输入",text_log.text)
        self.assertIn("缓存返回",text_log.text)
        self.assertIn("缓存组件验收",text_log.text)
        self.assertNotIn("offline-only",text_log.text)
        self.client.post("/api/auth/logout",json={})
        self.account("log_reader")
        self.assertEqual(self.client.get(f"/api/sessions/{session}/log").status_code,404)

    def test_static_files_and_no_credential_leak(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/web/app.js").status_code, 200)
        self.assertEqual(self.client.get("/web/.env").status_code, 404)
        self.assertEqual(self.client.get("/web/../data/assistant.sqlite3").status_code, 404)
        self.assertEqual(self.client.post("/api/auth/register",json={"username":"bad","password":"short"}).status_code, 422)
        self.assertEqual(self.client.get("/api/health",headers={"Host":"evil.invalid"}).status_code, 400)

    def test_real_context_failure_has_no_half_turn_or_model_call(self):
        user = self.account()
        session = self.client.post("/api/sessions",json={}).json()["id"]
        store = Records(self.root/"data/assistant.sqlite3")
        store.append(user["id"],session,"很长"*13000,"旧回复",0)
        store.close()
        with patch("hearthstone_assistant.agents.run.collect_reply",side_effect=AssertionError("不允许联网")), patch("hearthstone_assistant.memory.context.stream_reply",side_effect=AssertionError("不允许摘要联网")):
            response = self.client.post(f"/api/sessions/{session}/turns",json={"question":"继续","request_id":"b"*32})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertTrue(any(e["type"]=="turn_failed" for e in events))
        self.assertEqual(len(self.client.get(f"/api/sessions/{session}/messages").json()["turns"]),1)
        turn_id = events[0]["turn_id"]
        self.assertEqual(self.client.get(f"/api/sessions/{session}/turns/{turn_id}").json()["status"],"failed")

    def test_cancel_waiting_cache_task_does_not_affect_other_session(self):
        async def check():
            repo = Repository(self.root)
            user = (await repo.call("register","cancel_user","test-password-123"))["id"]
            a,b = await repo.call("create",user), await repo.call("create",user)
            key = request_key(self.settings,compose([],"缓存验收",{"through_turn":0,"text":""}))
            for session in (a,b):
                await repo.call("cache_answer",user,session,key,"仅用于缓存检查")
                await repo.call("begin_request",user,session,session,"hash",session,"0"*32)
            # 真队列背压让A等待；不使用假模型或模拟服务器。
            qa,qb = asyncio.Queue(maxsize=1),asyncio.Queue(maxsize=128)
            la,lb = WebLog(self.root/"data/logs",qa,user,a,a),WebLog(self.root/"data/logs",qb,user,b,b)
            task = asyncio.create_task(execute_turn(repo,self.settings,user,a,a,"缓存验收",True,qa,la))
            for _ in range(200):
                if la.path.exists() and "answer_cache" in la.path.read_text(): break
                await asyncio.sleep(.01)
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            await execute_turn(repo,self.settings,user,b,b,"缓存验收",True,qb,lb)
            self.assertEqual((await repo.call("request_status",user,a,a))["status"],"cancelled")
            self.assertEqual(await repo.call("turns",user,a),[])
            self.assertEqual((await repo.call("request_status",user,b,b))["status"],"completed")
        with patch("hearthstone_assistant.agents.run.collect_reply",side_effect=AssertionError("不允许模型联网")):
            asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
