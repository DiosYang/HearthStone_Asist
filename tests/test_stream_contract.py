"""只检查真实框架对象和拓扑，不调用或模拟模型服务。"""
import unittest
from langchain_core.messages import AIMessageChunk
from hearthstone_assistant.models.deepseek import text_piece,message_from_chunk
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

    def test_real_tool_graph_definition(self):
        edges = {(e.source, e.target) for e in build_graph(None, None, None).get_graph().edges}
        self.assertEqual(edges,{("__start__","model"),("model","tools"),("tools","model"),("model","__end__")})

    def test_tool_arguments_require_complete_json(self):
        part=AIMessageChunk(content="",tool_call_chunks=[{"name":"get_card","id":"test-call","args":'{"card_id":"CS2_',"index":0}])
        with self.assertRaises(ValueError): message_from_chunk(part)
        last=AIMessageChunk(content="",tool_call_chunks=[{"name":None,"id":None,"args":'029"}',"index":0}])
        reply=message_from_chunk(part+last)
        self.assertIn("CS2_029",reply["tool_calls"][0]["function"]["arguments"])
