"""仅配置测试；不联网，不读取真实.env。"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from hearthstone_assistant.config import load_settings


class ConfigTests(unittest.TestCase):
    def test_env_selection_and_secret_not_in_repr(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            parent = Path(temporary)
            root = parent / "project"
            root.mkdir()
            (parent / ".env").write_text("DEEPSEEK_API_KEY=test-parent\n", encoding="utf-8")
            settings = load_settings(root)
            self.assertEqual(settings.api_key, "test-parent")
            self.assertNotIn("test-parent", repr(settings))
            os.environ.pop("DEEPSEEK_API_KEY")
            (root / ".env").write_text("DEEPSEEK_API_KEY=test-local\n", encoding="utf-8")
            self.assertEqual(load_settings(root).api_key, "test-local")

    def test_reject_untrusted_model_host(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ,
                {"DEEPSEEK_BASE_URL": "https://example.invalid"}, clear=True):
            with self.assertRaises(ValueError):
                load_settings(Path(temporary) / "project")
