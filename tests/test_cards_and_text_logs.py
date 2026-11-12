"""纯数据校验+真实本地MCP；无模拟模型、无付费请求。"""
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from hearthstone_assistant.config import PROJECT_ROOT
from hearthstone_assistant.tools.cards.catalog import CardCatalog,SOURCE_URL,directory,snapshot,readable
from hearthstone_assistant.tools.cards.client import connect
from hearthstone_assistant.log import EventLog
from hearthstone_assistant.log.session import SessionLog,session_directory
from hearthstone_assistant.storage.sqlite import SessionStore
from hearthstone_assistant.memory.context import compose,estimate
from hearthstone_assistant.prompt.routing import profile,system_for


class CatalogChecks(unittest.TestCase):
    def test_search_ambiguity_ids_missing_fields_and_integrity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); target=directory(root); target.mkdir(parents=True)
            # 人工数据只验证纯检索逻辑，不冒充实际卡牌或模型回答。
            raw=json.dumps([{"id":"TEST_A","name":"测试卡","cost":0,"type":"SPELL","text":"<b>测试</b>：$6"},
                            {"id":"TEST_B","name":"测试卡","cost":1,"type":"SPELL"}],ensure_ascii=False).encode()
            digest=hashlib.sha256(raw).hexdigest()
            path=target/(digest+".json"); path.write_bytes(raw)
            (target/"manifest.json").write_text(json.dumps({"fingerprint":digest,"source_url":SOURCE_URL,"locale":"zhCN"}))
            catalog=CardCatalog(root)
            self.assertEqual(catalog.search("测试卡")["status"],"ambiguous")
            result=catalog.get("TEST_A")["card"]
            self.assertEqual(result["cost"],0)
            self.assertNotIn("health",result)
            self.assertEqual(result["text"],"测试：6")
            self.assertEqual(catalog.get("../.env")["status"],"not_found")
            path.write_bytes(b"[]")
            with self.assertRaises(ValueError): CardCatalog(root)

    def test_task_prompt_selection_is_not_permission(self):
        self.assertEqual(profile("查询火球术效果"),"card_lookup")
        self.assertEqual(profile("解释套牌风格"),"deck_discussion")
        self.assertIn("search_cards",system_for("你好"))
        self.assertIn("HearthstoneJSON",system_for("查询卡牌"))


class TranscriptAndLogChecks(unittest.TestCase):
    def test_readable_log_appends_per_session_and_redacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            log=SessionLog(root,"alice","session-a","turn-1",secrets=("sensitive-test-secret",))
            log.emit("turn_start")
            log.detail("请求",{"messages":[{"role":"user","content":"查询卡牌 sensitive-test-secret"}],
                              "headers":{"Authorization":"Bearer private"},"password":"never-save"})
            SessionLog(root,"alice","session-a","turn-2").detail("返回",{"content":"测试结果"})
            other=SessionLog(root,"bob","session-a","turn-3")
            other.detail("请求",{"content":"另一个用户"})
            text=log.text_path.read_text()
            self.assertIn("turn-1",text);self.assertIn("turn-2",text)
            self.assertIn("查询卡牌",text);self.assertIn("测试结果",text)
            self.assertNotIn("sensitive-test-secret",text);self.assertNotIn("never-save",text)
            self.assertNotIn("另一个用户",text)
            with self.assertRaises(ValueError): session_directory(root,"../alice","s")

    def test_tool_chain_persistence_and_old_schema_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"old.sqlite3"
            old=sqlite3.connect(path)
            old.execute("CREATE TABLE turns(user_id TEXT,session_id TEXT,number INTEGER,question TEXT,answer TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(user_id,session_id,number))")
            old.close()
            store=SessionStore(path); session=store.create("alice")
            chain=[{"role":"user","content":"查卡"},
                   {"role":"assistant","content":None,"tool_calls":[{"id":"test-call","type":"function","function":{"name":"get_card","arguments":'{"card_id":"TEST_A"}'}}]},
                   {"role":"tool","tool_call_id":"test-call","content":'{"ok":true}'},
                   {"role":"assistant","content":"已查询"}]
            with self.assertRaises(ValueError): store.append("alice",session,"查卡","已查询",0,chain[:2]+chain[-1:])
            store.append("alice",session,"查卡","已查询",0,chain)
            turns=store.turns("alice",session)
            self.assertEqual(turns[0]["messages"],chain)
            messages=compose(turns,"继续",{"through_turn":0,"text":""})
            self.assertEqual([m["role"] for m in messages],["system","user","assistant","tool","assistant","user"])
            self.assertGreater(estimate(messages),4096)
            store.close()


@unittest.skipUnless(snapshot(PROJECT_ROOT).get("fingerprint"),"需先下载真实卡库，测试不自动联网")
class RealMCPChecks(unittest.TestCase):
    def test_real_server_reads_snapshot_and_refuses_extra_parameters(self):
        async def check(log):
            async with connect(SimpleNamespace(project_root=PROJECT_ROOT),log,snapshot(PROJECT_ROOT)["fingerprint"]) as tools:
                found=await tools.execute("search_cards",{"query":"火球术"})
                self.assertTrue(found["ok"])
                self.assertTrue(found["cards"])
                card_id=found["cards"][0]["id"]
                detail=await tools.execute("get_card",{"card_id":card_id})
                self.assertEqual(detail["card"]["id"],card_id)
                self.assertIsNone(detail["card"]["standard_legal"])
                denied=await tools.execute("search_cards",{"query":"火球术","url":"https://example.invalid"})
                self.assertFalse(denied["ok"])
        with tempfile.TemporaryDirectory() as folder:
            asyncio.run(check(EventLog(Path(folder),console=False)))
