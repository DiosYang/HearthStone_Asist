from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from hearthstone_assistant.cache.answers import request_key
from hearthstone_assistant.storage.sqlite import SessionStore


class CacheTests(unittest.TestCase):
    def test_context_and_model_affect_key(self):
        settings = SimpleNamespace(model="a", base_url="https://api.deepseek.com")
        first = request_key(settings, [{"role": "user", "content": "问题"}])
        self.assertEqual(first, request_key(settings, [{"role": "user", "content": "问题"}]))
        self.assertNotEqual(first, request_key(settings, [{"role": "user", "content": "另一个问题"}]))
        settings.model = "b"
        self.assertNotEqual(first, request_key(settings, [{"role": "user", "content": "问题"}]))

    def test_scope_expiry_and_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "test.sqlite3")
            a1, a2, b1 = store.create("alice"), store.create("alice"), store.create("bob")
            store.cache_answer("alice", a1, "key", "answer")
            self.assertEqual(store.cached_answer("alice", a1, "key"), "answer")
            self.assertIsNone(store.cached_answer("alice", a2, "key"))
            self.assertIsNone(store.cached_answer("bob", b1, "key"))
            with self.assertRaises(ValueError):
                store.cached_answer("bob", a1, "key")
            store.cache_answer("alice", a1, "expired", "old", ttl=-1)
            self.assertIsNone(store.cached_answer("alice", a1, "expired"))
            store.close()
