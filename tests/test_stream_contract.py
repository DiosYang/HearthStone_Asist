"""只检查真实框架对象和拓扑，不调用或模拟模型服务。"""
import unittest
from langchain_core.messages import AIMessageChunk
from hearthstone_assistant.models.deepseek import text_piece
from hearthstone_assistant.agents.run import build_graph


class StreamTests(unittest.TestCase):
    def test_text_piece_contract(self):
        self.assertEqual(text_piece(AIMessageChunk(content="炉石")), "炉石")
        self.assertEqual(text_piece(AIMessageChunk(content="")), "")

    def test_no_tool_execution_in_text_only_stage(self):
        chunk = AIMessageChunk(content="", tool_call_chunks=[
            {"name": "test", "id": "test-id", "args": "{}", "index": 0}])
        with self.assertRaises(ValueError):
            text_piece(chunk)

    def test_single_real_graph_definition(self):
        edges = {(e.source, e.target) for e in build_graph(None, None, None).get_graph().edges}
        self.assertEqual(edges, {("__start__", "model"), ("model", "__end__")})
