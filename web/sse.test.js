import {test} from 'node:test';
import assert from 'node:assert/strict';
import {consumeSSE} from './sse.js';

test('真实ReadableStream按单字节拆分中文、CRLF和多个SSE事件',async()=>{
  const bytes=new TextEncoder().encode(': keep-alive\r\ndata: {"type":"text_delta",\r\ndata: "text":"炉石"}\r\n\r\ndata: {"type":"turn_completed"}\n\n');
  const stream=new ReadableStream({start(controller){for(const byte of bytes)controller.enqueue(new Uint8Array([byte]));controller.close();}});
  const events=[];await consumeSSE(stream,event=>events.push(event));
  assert.deepEqual(events,[{type:'text_delta',text:'炉石'},{type:'turn_completed'}]);
});
test('缺少事件结束空行不派发半截事件',async()=>{
  const stream=new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('data: {"unfinished":true}\n'));c.close();}});
  const events=[];await consumeSSE(stream,event=>events.push(event));assert.deepEqual(events,[]);
});
