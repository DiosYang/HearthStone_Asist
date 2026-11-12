import json
from pathlib import Path
import tempfile
import unittest
from hearthstone_assistant.log import EventLog


class LogTests(unittest.TestCase):
    def test_records_share_run_and_have_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            log = EventLog(directory)
            log.emit("run_start")
            log.emit("run_end", status="ok")
            rows = [json.loads(line) for line in log.path.read_text().splitlines()]
            self.assertEqual([r["sequence"] for r in rows], [1, 2])
            self.assertEqual(rows[0]["run_id"], rows[1]["run_id"])

    def test_key_and_full_messages_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as directory:
            log = EventLog(directory)
            for field in ("api_key", "headers", "messages"):
                with self.assertRaises(ValueError):
                    log.emit("test", **{field: "private-test-value"})
            self.assertEqual(list(Path(directory).glob("*.jsonl")), [])
