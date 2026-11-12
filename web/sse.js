// UTF-8解码器跨网络chunk保留状态；SSE按空行派发，不把chunk当事件。
export async function consumeSSE(body, onEvent) {
  if (!body) throw new Error('服务端未返回数据流');
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '', data = [];
  async function line(value) {
    if (value.endsWith('\r')) value = value.slice(0, -1);
    if (value === '') {
      if (data.length) { const payload = data.join('\n'); data = []; await onEvent(JSON.parse(payload)); }
    } else if (value.startsWith('data:')) {
      let valuePart = value.slice(5); if (valuePart.startsWith(' ')) valuePart = valuePart.slice(1);
      data.push(valuePart);
    }
  }
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, {stream: true});
      let position;
      while ((position = buffer.indexOf('\n')) !== -1) {
        const next = buffer.slice(0, position); buffer = buffer.slice(position + 1); await line(next);
      }
      if (buffer.length > 1_000_000) throw new Error('流式事件过大');
      if (done) break;
    }
    // 未以空行结束的事件不视为完整，调用方另外核对业务终态。
  } finally { reader.releaseLock(); }
}
