import {consumeSSE} from './sse.js';

const $ = id => document.getElementById(id);
const state = {user: null, session: null, sessions: [], busy: false, controller: null, turn: null, authMode: 'login', tokenTotal: 0, timeTotal: 0, traceCount: 0};
const labels = {turn_start:'任务开始',context_selected:'选取对话上下文',summary_start:'开始压缩旧对话',summary_saved:'摘要已保存',memory_injected:'参考已确认的偏好',answer_cache:'检查回答缓存',graph_node_start:'进入模型节点',model_request:'发起模型请求',first_text:'收到首个可见文本',model_stream_end:'模型流结束',graph_node_end:'模型节点完成',session_saved:'完整对话已保存',turn_cancelled:'当前任务已取消',turn_failed:'任务未完成',cache_write_failed:'缓存写入失败（历史已保留）'};

function toast(message) { $('toast').textContent = message; $('toast').classList.remove('hidden'); clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').classList.add('hidden'), 5500); }
function showAuth() { if (!$('auth-dialog').open) $('auth-dialog').showModal(); }
function scrollDown() { const box = $('chat-scroll'); box.scrollTop = box.scrollHeight; }
async function api(path, options = {}) {
  const response = await fetch('/api' + path, {credentials:'same-origin', ...options, headers:{'Content-Type':'application/json',...options.headers}, body: options.body === undefined ? undefined : JSON.stringify(options.body)});
  const value = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !path.includes('/auth/login')) showAuth();
    const detail = typeof value.detail === 'string' ? value.detail : value.detail?.message;
    throw new Error(detail || '请求失败，请稍后再试');
  }
  return value;
}
function setBusy(busy) {
  state.busy = busy;
  $('send').classList.toggle('hidden', busy); $('stop').classList.toggle('hidden', !busy);
  $('question').disabled = busy; $('use-cache').disabled = busy; $('new-chat').disabled = busy;
  $('profile').disabled = busy;
  document.querySelectorAll('.session-button,.suggestion').forEach(button => button.disabled = busy);
  $('composer-status').textContent = busy ? '正在认真想这一手…' : '准备好，一起想一想';
  $('run-state').classList.toggle('active', busy);
  $('run-state').textContent = busy ? '运行中' : '已结束';
}
function resetInspector() {
  state.tokenTotal = 0; state.timeTotal = 0; state.traceCount = 0;
  $('trace').replaceChildren(); $('trace-count').textContent = '0';
  $('metric-first').textContent = '—'; $('metric-time').textContent = '—'; $('metric-tokens').textContent = '—';
  $('metric-cache').textContent = '未检查'; $('context-progress').value = 0;
  $('context-used').textContent = '— / 24,000'; $('run-id').textContent = '准备开始';
  $('summary-note').textContent = '历史变长时按预算摘要；原始对话仍保留。';
}
function observe(event) {
  const item = document.createElement('li'); item.textContent = labels[event.event] || event.event;
  const small = document.createElement('small');
  small.textContent = [event.stage === 'summary' ? '摘要请求（单独计费）' : '', event.status || '', event.seconds !== undefined ? `${event.seconds}s` : ''].filter(Boolean).join(' · ');
  if (small.textContent) item.append(small);
  $('trace').append(item); state.traceCount++; $('trace-count').textContent = state.traceCount;
  $('trace').scrollTop = $('trace').scrollHeight;
  if (event.event === 'first_text' && event.stage === 'chat') $('metric-first').textContent = event.seconds.toFixed(3);
  if (event.event === 'model_stream_end') {
    state.timeTotal += event.seconds || 0; $('metric-time').textContent = state.timeTotal.toFixed(2);
    if (Number.isFinite(event.total_tokens)) { state.tokenTotal += event.total_tokens; $('metric-tokens').textContent = state.tokenTotal.toLocaleString(); }
  }
  if (event.event === 'context_selected') {
    $('context-progress').max = event.budget; $('context-progress').value = event.estimate_units;
    $('context-used').textContent = `${event.estimate_units.toLocaleString()} / ${event.budget.toLocaleString()}`;
    $('summary-note').textContent = event.summary_used ? `已使用旧对话摘要，覆盖至第 ${event.summary_through} 轮。原文仍在历史中。` : '当前使用原始对话上下文，尚不需要摘要。';
  }
}
function bubble(role, content = '', status = '') {
  const element = document.createElement('article'); element.className = `message ${role}`;
  const avatar = document.createElement('span'); avatar.className = 'message-avatar'; avatar.textContent = role === 'user' ? state.user.username[0].toUpperCase() : '炉';
  const wrap = document.createElement('div'); wrap.className = 'message-content';
  const title = document.createElement('div'); title.className = 'message-name'; title.textContent = role === 'user' ? '你' : '炉边';
  const badge = document.createElement('small'); badge.textContent = role === 'user' ? 'USER' : 'HEARTHSIDE'; title.append(badge);
  const text = document.createElement('div'); text.className = 'message-text'; text.textContent = content;
  const hint = document.createElement('div'); hint.className = 'message-status'; hint.textContent = status;
  wrap.append(title, text, hint); element.append(avatar, wrap); $('messages').append(element);
  $('welcome').classList.add('hidden'); scrollDown();
  return {element,text,hint};
}
function renderSessions() {
  const filter = $('session-search').value.trim().toLowerCase();
  $('sessions').replaceChildren(); $('session-count').textContent = state.sessions.length;
  for (const session of state.sessions.filter(s => (s.title || '新对话').toLowerCase().includes(filter))) {
    const button = document.createElement('button'); button.className = 'session-button'; button.disabled = state.busy;
    if (session.id === state.session) button.classList.add('active');
    const icon = document.createElement('span'); icon.className = 'session-symbol'; icon.textContent = '▱';
    const text = document.createElement('span'); text.className = 'session-text'; text.textContent = session.title || '新对话'; button.title = text.textContent;
    button.append(icon,text); button.addEventListener('click', () => selectSession(session.id).catch(e => toast(e.message))); $('sessions').append(button);
  }
  if (!$('sessions').childElementCount) {
    const empty = document.createElement('p'); empty.className = 'sidebar-empty'; empty.textContent = filter ? '没有找到这段对话。' : '你的第一段炉边对话，从一个问题开始。'; $('sessions').append(empty);
  }
}
async function refreshSessions() { const value = await api('/sessions'); state.sessions = value.sessions; renderSessions(); }
async function selectSession(id) {
  if (state.busy) return;
  const value = await api(`/sessions/${id}/messages`); state.session = id;
  localStorage.setItem(`hearth-session-${state.user.id}`, id);
  $('messages').replaceChildren(); $('welcome').classList.toggle('hidden', value.turns.length > 0);
  for (const turn of value.turns) { bubble('user',turn.question); bubble('assistant',turn.answer,'已保存的完整回复'); }
  $('chat-title').textContent = value.turns.length ? value.turns[0].question.slice(0,28) : '每一手，都值得想一想。';
  renderSessions(); $('sidebar').classList.remove('mobile-open'); resetInspector(); $('run-state').textContent = '历史会话';
}
function newConversation() {
  if (state.busy) return;
  state.session = null; state.turn = null; if (state.user) localStorage.removeItem(`hearth-session-${state.user.id}`);
  $('messages').replaceChildren(); $('welcome').classList.remove('hidden'); $('question').value = '';
  $('chat-title').textContent = '每一手，都值得想一想。'; renderSessions(); resetInspector(); $('run-state').textContent = '待开始';
  $('sidebar').classList.remove('mobile-open'); $('question').focus();
}
async function afterLogin(user) {
  state.user = user; $('username').textContent = user.username; $('user-avatar').textContent = user.username[0].toUpperCase();
  if ($('auth-dialog').open) $('auth-dialog').close();
  const me = await api('/auth/me'); $('model-name').textContent = me.model;
  if (!me.model_configured) toast('服务端尚未配置DeepSeek Key，请先运行doctor。');
  await refreshSessions(); const saved = localStorage.getItem(`hearth-session-${user.id}`);
  if (saved && state.sessions.some(s => s.id === saved)) await selectSession(saved); else newConversation();
}
function authMode(mode) {
  state.authMode = mode; $('login-tab').classList.toggle('active', mode === 'login'); $('register-tab').classList.toggle('active', mode === 'register');
  $('auth-title').textContent = mode === 'login' ? '欢迎回到你的酒馆' : '留一个属于你的炉边位置';
  $('auth-description').textContent = mode === 'login' ? '登录后，继续你的思考与对话。' : '创建本地助手账号，独立保存你的对话与偏好。';
  $('auth-password').autocomplete = mode === 'login' ? 'current-password' : 'new-password';
  $('auth-submit').textContent = mode === 'login' ? '进入炉边 →' : '创建账号并进入 →'; $('auth-error').textContent = '';
}
async function send() {
  if (!state.user) { showAuth(); return; }
  const question = $('question').value.trim(); if (!question || state.busy) return;
  setBusy(true); resetInspector(); state.turn = null;
  let assistant, complete = false;
  try {
    if (!state.session) { const value = await api('/sessions',{method:'POST',body:{}}); state.session = value.id; localStorage.setItem(`hearth-session-${state.user.id}`,value.id); }
    bubble('user',question); assistant = bubble('assistant','','正在准备上下文…'); assistant.text.classList.add('stream-cursor');
    $('question').value = ''; $('chat-title').textContent = state.sessions.find(s => s.id === state.session)?.title?.slice(0,28) || question.slice(0,28);
    await refreshSessions(); state.controller = new AbortController();
    const response = await fetch(`/api/sessions/${state.session}/turns`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},signal:state.controller.signal,body:JSON.stringify({question,request_id:crypto.randomUUID(),use_cache:$('use-cache').checked})});
    if (!response.ok) { const error = await response.json(); throw new Error(typeof error.detail === 'string' ? error.detail : error.detail?.message || '请求未被接受'); }
    await consumeSSE(response.body, async event => {
      if (event.type === 'turn_started') { state.turn = event.turn_id; $('run-id').textContent = event.run_id || `重放已完成请求 ${event.turn_id.slice(0,12)}`; }
      if (event.type === 'trace') observe(event);
      if (event.type === 'cache') { $('metric-cache').textContent = event.hit ? '命中（未重新问答）' : '未命中'; if (event.hit) assistant.hint.textContent = '来自相同上下文的有效缓存'; }
      if (event.type === 'text_delta') { assistant.hint.textContent = '流式生成中…'; assistant.text.textContent += event.text; scrollDown(); }
      if (event.type === 'turn_completed') { complete = true; assistant.hint.textContent = event.replayed ? '已完成请求重放 · 未重复请求模型' : event.cached ? '缓存回答 · 完整会话已保存' : '回复完成 · 完整会话已保存'; }
      if (event.type === 'turn_failed') throw new Error(event.message || '本轮未完成');
      if (event.type === 'cancelled') throw new DOMException('已取消','AbortError');
    });
    if (!complete) throw new Error('连接已结束，尚未收到保存确认；正在核对状态。');
  } catch (error) {
    if (state.turn && state.session) {
      try {
        const status = await api(`/sessions/${state.session}/turns/${state.turn}`);
        if (status.status === 'completed' && assistant) { complete = true; assistant.text.textContent = status.answer; assistant.hint.textContent = '已核对服务端：完整回复已保存'; }
      } catch { /* 无法核对时不自动重发，保留不确定状态。 */ }
    }
    if (!complete) {
      const message = error.name === 'AbortError' ? '已停止；部分文字不作为完整对话保存。' : error.message;
      if (assistant) { assistant.hint.textContent = message; assistant.element.classList.add('incomplete'); } else toast(message);
      $('run-state').textContent = '未完成';
    }
  } finally {
    if (assistant) assistant.text.classList.remove('stream-cursor');
    state.controller = null; setBusy(false); $('run-state').textContent = complete ? '已保存' : '未完成';
    try { await refreshSessions(); } catch { /* 登录已失效会由api提示。 */ }
    $('question').focus();
  }
}
async function stop() {
  if (!state.busy) return;
  $('stop').disabled = true;
  try { if (state.turn) await api(`/sessions/${state.session}/turns/${state.turn}/cancel`,{method:'POST',body:{}}); }
  catch (error) { toast(error.message); }
  finally { state.controller?.abort(); $('stop').disabled = false; }
}
async function openPreferences() {
  if (!state.user) { showAuth(); return; }
  const value = await api('/preferences');
  for (const input of $('preferences-form').querySelectorAll('input')) input.value = value.preferences[input.name] || '';
  $('preferences-error').textContent = ''; $('preferences-dialog').showModal();
}
async function savePreferences(values) {
  await api('/preferences',{method:'PUT',body:values}); $('preferences-dialog').close(); toast('偏好已更新，后续相关对话会参考。');
}

$('auth-form').addEventListener('submit',async event => { event.preventDefault(); $('auth-submit').disabled = true; $('auth-error').textContent = ''; try { const value = await api(`/auth/${state.authMode}`,{method:'POST',body:{username:$('auth-username').value.trim(),password:$('auth-password').value}}); $('auth-password').value = ''; await afterLogin(value.user); } catch(error) { $('auth-error').textContent = error.message; } finally { $('auth-submit').disabled = false; } });
$('auth-dialog').addEventListener('cancel',event => event.preventDefault());
$('login-tab').addEventListener('click',()=>authMode('login')); $('register-tab').addEventListener('click',()=>authMode('register'));
$('send').addEventListener('click',send); $('stop').addEventListener('click',stop); $('new-chat').addEventListener('click',newConversation);
$('question').addEventListener('keydown',event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send(); } });
$('session-search').addEventListener('input',renderSessions);
document.querySelectorAll('.suggestion').forEach(button => button.addEventListener('click',()=>{ $('question').value=button.dataset.prompt; $('question').focus(); }));
$('profile').addEventListener('click',()=>openPreferences().catch(error=>toast(error.message)));
$('close-preferences').addEventListener('click',()=>$('preferences-dialog').close());
$('preferences-form').addEventListener('submit',async event=>{event.preventDefault();$('save-preferences').disabled=true;try { await savePreferences(Object.fromEntries(new FormData(event.target))); } catch(error) { $('preferences-error').textContent=error.message; } finally { $('save-preferences').disabled=false; }});
$('clear-preferences').addEventListener('click',async()=>{if(confirm('删除全部已保存偏好？旧聊天和日志不会删除。')) { try { await savePreferences({}); } catch(error) { $('preferences-error').textContent=error.message; } }});
$('logout').addEventListener('click',async()=>{try{if(state.busy) await stop();await api('/auth/logout',{method:'POST',body:{}});state.user=null;state.session=null;state.sessions=[];$('messages').replaceChildren();$('welcome').classList.remove('hidden');$('username').textContent='尚未登录';$('user-avatar').textContent='?';renderSessions();resetInspector();showAuth();}catch(error){toast(error.message);}});
$('toggle-inspector').addEventListener('click',()=>{const narrow=matchMedia('(max-width:1000px)').matches;const open=narrow ? $('inspector').classList.toggle('mobile-open') : !$('inspector').classList.toggle('is-hidden');$('toggle-inspector').setAttribute('aria-expanded',String(open));});
$('menu').addEventListener('click',()=>$('sidebar').classList.toggle('mobile-open'));
document.addEventListener('keydown',event=>{if(event.altKey&&event.key.toLowerCase()==='n'){event.preventDefault();newConversation();}});
document.addEventListener('click',event=>{if(!event.target.closest('#sidebar')&&!event.target.closest('#menu'))$('sidebar').classList.remove('mobile-open');});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){$('sidebar').classList.remove('mobile-open');$('inspector').classList.remove('mobile-open');}});
try { const value = await api('/auth/me'); await afterLogin(value.user); }
catch { showAuth(); }
