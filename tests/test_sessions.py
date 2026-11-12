import asyncio
import copy
import json
import tempfile
from pathlib import Path
import unittest
from hearthstone_assistant.storage.sqlite import SessionStore
from hearthstone_assistant.memory.context import compose, estimate,turn_context,prepare_context,SummaryBudget
from hearthstone_assistant.agents.run import select_model_context
from hearthstone_assistant.log import EventLog


class SessionTests(unittest.TestCase):
    def test_user_and_session_isolation_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            store = SessionStore(path)
            a1, a2, b1 = store.create("alice"), store.create("alice"), store.create("bob")
            store.append("alice", a1, "问题", "回复", 0)
            self.assertEqual(store.turns("alice", a2), [])
            self.assertEqual(store.turns("bob", b1), [])
            for operation in (lambda: store.turns("bob", a1),
                              lambda: store.append("bob", a1, "q", "a", 1),
                              lambda: store.summary("bob", a1),
                              lambda: store.save_summary("bob", a1, "text", 1, 0)):
                with self.assertRaises(ValueError):
                    operation()
            self.assertNotIn(a1, [r["id"] for r in store.list("bob")])
            with self.assertRaises(ValueError):
                store.append("alice", a1, "旧快照", "回复", 0)
            store.save_summary("alice", a1, "测试摘要", 1, 0)
            store.close()
            reopened = SessionStore(path)
            self.assertEqual(len(reopened.turns("alice", a1)), 1)
            self.assertEqual(reopened.summary("alice", a1)["text"], "测试摘要")
            with self.assertRaises(ValueError):
                reopened.save_summary("alice", a1, "过期摘要", 1, 0)
            reopened.close()

    def test_context_preserves_pairs_and_uses_only_unsummarized_turns(self):
        turns = [{"number": 1, "question": "旧问题", "answer": "旧回复"},
                 {"number": 2, "question": "新问题", "answer": "新回复"}]
        messages = compose(turns, "继续", {"through_turn": 1, "text": "摘要"})
        self.assertEqual([m["role"] for m in messages], ["system", "user", "user", "assistant", "user"])
        self.assertNotIn("旧问题", [m["content"] for m in messages])
        self.assertGreater(estimate(messages), 4096)

    def test_tool_growth_reselects_history_and_preserves_complete_active_chain(self):
        # 真实SQLite+纯上下文构造；预存摘要只作为数据，不模拟模型响应。
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=SessionStore(root/"context.sqlite3")
            session=store.create("alice")
            store.append("alice",session,"先前的问题","先前的回答。"*800,0)
            turns=store.turns("alice",session)
            question="比较两张卡";current=[{"role":"user","content":question}]
            injected=[{"role":"user","content":"已保存的偏好：简洁中文"}]
            budget=estimate(compose(turns,question,{"through_turn":0,"text":""}))+1000
            log=EventLog(root/"logs",console=False)
            select=turn_context(None,store,"alice",session,turns,question,log,
                                injected=injected,tool_units=300,budget=budget)
            initial=asyncio.run(select(current))
            store.save_summary("alice",session,"旧轮次的已存摘要",1,0)
            calls=[{"id":f"call-{i}","type":"function","function":{"name":"get_card","arguments":json.dumps({"card_id":str(i)})}} for i in range(2)]
            current += [{"role":"assistant","content":None,"tool_calls":calls}]
            current += [{"role":"tool","tool_call_id":f"call-{i}","content":"卡牌详情"*300} for i in range(2)]
            original=initial+current[1:];saved=copy.deepcopy(original)
            self.assertGreater(estimate(original)+300,budget)
            chosen=asyncio.run(select_model_context(original,len(initial)-1,select,log,300,budget))
            self.assertLessEqual(estimate(chosen)+300,budget)
            self.assertEqual(chosen[-len(current):],current)
            self.assertIn(injected[0],chosen)
            self.assertEqual(original,saved)
            self.assertEqual(len(store.turns("alice",session)),1)
            self.assertIn("context_limit",log.path.read_text())
            store.close()

    def test_active_tool_chain_too_large_stops_before_model_or_history_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=SessionStore(root/"context.sqlite3")
            session=store.create("alice");log=EventLog(root/"logs",console=False)
            question="查卡"
            current=[{"role":"user","content":question},
                     {"role":"assistant","content":None,"tool_calls":[{"id":"call-1"}]},
                     {"role":"tool","tool_call_id":"call-1","content":"大结果"*10000}]
            select=turn_context(None,store,"alice",session,[],question,log)
            with self.assertRaisesRegex(ValueError,"当前工具上下文超过预算"):
                asyncio.run(select(current))
            self.assertEqual(store.turns("alice",session),[])
            self.assertEqual(store.summary("alice",session)["through_turn"],0)
            store.append("alice",session,"旧问题","旧回答",0)
            store.save_summary("alice",session,"摘要"*400,1,0)
            short=copy.deepcopy(current);short[-1]["content"]="短卡牌结果"
            available=estimate(compose([],question,{"through_turn":0,"text":""}))+100
            from hearthstone_assistant.memory.context import message_units
            select=turn_context(None,store,"alice",session,store.turns("alice",session),question,log,
                                budget=available+message_units(short[1:]))
            with self.assertRaisesRegex(ValueError,"已有摘要合计超过预算"):
                asyncio.run(select(short))
            self.assertEqual(len(store.turns("alice",session)),1)
            store.close()

    def test_summary_budget_cannot_reset_for_followup_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=SessionStore(root/"context.sqlite3")
            session=store.create("alice")
            store.append("alice",session,"旧问题","长回答"*1000,0)
            limit=SummaryBudget(used=3)
            budget=estimate(compose([],"继续",{"through_turn":0,"text":""}))+100
            with self.assertRaisesRegex(ValueError,"3次摘要预算"):
                asyncio.run(prepare_context(None,store,"alice",session,store.turns("alice",session),"继续",
                                            EventLog(root/"logs",console=False),budget,limit))
            self.assertEqual(limit.used,3)
            store.close()
