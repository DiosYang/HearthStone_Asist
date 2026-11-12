import tempfile
from pathlib import Path
import unittest
from hearthstone_assistant.storage.sqlite import SessionStore
from hearthstone_assistant.memory.context import compose, estimate


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
