"""本机同源CS服务，单worker；认证用户由HttpOnly会话Cookie确定。"""
import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import time
import uuid
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field
from hearthstone_assistant.config import PROJECT_ROOT, load_settings
from hearthstone_assistant.server.repository import Repository
from hearthstone_assistant.server.service import WebLog, execute_turn

COOKIE = "hearth_session"
WEB = PROJECT_ROOT / "web"


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(pattern=r"^[A-Za-z0-9_]{3,32}$")
    password: str = Field(min_length=10, max_length=128)


class TurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(pattern=r"^[a-f0-9-]{32,36}$")
    use_cache: bool = True


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    favorite_class: str = Field(default="", max_length=60)
    play_style: str = Field(default="", max_length=100)
    budget: str = Field(default="", max_length=100)
    answer_style: str = Field(default="", max_length=100)


def sse(value):
    return "data: " + json.dumps(value, ensure_ascii=False) + "\n\n"


def create_app(root=PROJECT_ROOT, settings=None):
    root = Path(root)
    repo = Repository(root)
    running = {}  # turn_id -> (task,user,session), bounded to four tasks
    gate = asyncio.Lock()
    attempts = defaultdict(deque)

    @asynccontextmanager
    async def lifespan(app):
        nonlocal settings
        if settings is None:
            settings = load_settings()
        await repo.call("initialize_web")
        yield
        tasks = [item[0] for item in running.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="炉边 · 炉石小助手", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def protect(request, call_next):
        if request.method in {"POST", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "不接受跨站操作"}, 403)
            length = request.headers.get("content-length", "0")
            if not length.isdigit() or int(length) > 32768:
                return JSONResponse({"detail": "请求过大"}, 413)
            if request.headers.get("transfer-encoding"):
                return JSONResponse({"detail": "请发送有长度的JSON请求"}, 411)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        return JSONResponse({"detail": "输入格式不正确；用户名3—32位字母/数字/下划线，密码至少10位，问题最多4000字。"}, 422)

    async def current_user(request: Request):
        token = request.cookies.get(COOKIE, "")
        user = await repo.call("authenticate", token) if token else None
        if not user:
            raise HTTPException(401, "请先登录")
        return user

    async def own(user, session):
        try:
            await repo.call("require", user["id"], session)
        except ValueError:
            raise HTTPException(404, "会话不存在") from None

    def throttle(request):
        now = time.monotonic()
        key = request.client.host if request.client else "local"
        if len(attempts) > 1024:
            for address in list(attempts):
                if not attempts[address] or attempts[address][-1] < now-60:
                    del attempts[address]
            if len(attempts) > 1024:
                raise HTTPException(429, "请稍后再试")
        recent = attempts[key]
        while recent and recent[0] < now-60:
            recent.popleft()
        if len(recent) >= 8:
            raise HTTPException(429, "尝试过于频繁，请一分钟后再试")
        recent.append(now)

    async def enter(user, request):
        token = await repo.call("issue_login", user["id"])
        response = JSONResponse({"user": user})
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https", max_age=86400)
        return response

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "model_configured": bool(settings.api_key)}

    @app.post("/api/auth/register", status_code=201)
    async def register(body: Credentials, request: Request):
        throttle(request)
        try:
            user = await repo.call("register", body.username.lower(), body.password)
        except ValueError:
            raise HTTPException(409, "用户名已存在") from None
        return await enter(user, request)

    @app.post("/api/auth/login")
    async def login(body: Credentials, request: Request):
        throttle(request)
        user = await repo.call("login", body.username.lower(), body.password)
        if not user:
            raise HTTPException(401, "用户名或密码不正确")
        return await enter(user, request)

    @app.get("/api/auth/me")
    async def me(user=Depends(current_user)):
        return {"user": user, "model": settings.model, "model_configured": bool(settings.api_key)}

    @app.post("/api/auth/logout")
    async def logout(request: Request, user=Depends(current_user)):
        # 退出同时取消该账号正在进行的请求，等待资源清理。
        tasks = [item[0] for item in running.values() if item[1] == user["id"]]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await repo.call("logout", request.cookies[COOKIE])
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE)
        return response

    @app.get("/api/sessions")
    async def sessions(user=Depends(current_user)):
        return {"sessions": await repo.call("session_list", user["id"])}

    @app.post("/api/sessions")
    async def new_session(user=Depends(current_user)):
        return {"id": await repo.call("create", user["id"])}

    @app.get("/api/sessions/{session}/messages")
    async def messages(session: str, user=Depends(current_user)):
        await own(user, session)
        return {"turns": await repo.call("turns", user["id"], session)}

    @app.get("/api/preferences")
    async def preferences(user=Depends(current_user)):
        return {"preferences": await repo.call("get_preferences", user["id"])}

    @app.put("/api/preferences")
    async def save_preferences(body: Preferences, user=Depends(current_user)):
        await repo.call("put_preferences", user["id"], body.model_dump())
        return {"ok": True}

    @app.get("/api/sessions/{session}/turns/{turn_id}")
    async def turn_status(session: str, turn_id: str, user=Depends(current_user)):
        try:
            return await repo.call("request_status", user["id"], session, turn_id)
        except ValueError:
            raise HTTPException(404, "任务不存在") from None

    @app.get("/api/sessions/{session}/turns/{turn_id}/events")
    async def events(session: str, turn_id: str, user=Depends(current_user)):
        state = await turn_status(session, turn_id, user)
        def read():
            run_id = state["run_id"]
            if not run_id or len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
                return []
            path = root / "data" / "logs" / (run_id + ".jsonl")
            if not path.exists():
                return []
            return [json.loads(line) for line in path.read_text().splitlines()][-200:]
        return {"events": await asyncio.to_thread(read)}

    @app.post("/api/sessions/{session}/turns/{turn_id}/cancel")
    async def cancel(session: str, turn_id: str, user=Depends(current_user)):
        await turn_status(session, turn_id, user)
        item = running.get(turn_id)
        if item and item[1:] == (user["id"], session):
            item[0].cancel()
            await asyncio.gather(item[0], return_exceptions=True)
        return await turn_status(session, turn_id, user)

    @app.post("/api/sessions/{session}/turns")
    async def chat(session: str, body: TurnInput, request: Request, user=Depends(current_user)):
        await own(user, session)
        question = body.question.strip()
        if not question:
            raise HTTPException(422, "请输入问题")
        if not settings.api_key:
            raise HTTPException(503, "服务端尚未配置DeepSeek Key；请先运行doctor")
        fingerprint = hashlib.sha256(json.dumps([question,body.use_cache]).encode()).hexdigest()
        queue = asyncio.Queue(maxsize=128)
        turn_id = uuid.uuid4().hex
        log = WebLog(root / "data" / "logs", queue, user["id"], session, turn_id)
        async with gate:
            if any(item[1:] == (user["id"],session) for item in running.values()):
                raise HTTPException(409, "当前会话已有任务，请先等待或取消")
            if len(running) >= 4 or sum(item[1] == user["id"] for item in running.values()) >= 2:
                raise HTTPException(429, "并发任务已达上限，请稍后再试")
            try:
                old = await repo.call("begin_request", user["id"], session, body.request_id, fingerprint, turn_id, log.run_id)
            except ValueError:
                raise HTTPException(409, "请求编号已用于不同内容") from None
            if old:
                state = await turn_status(session, old["id"], user)
                if state["status"] != "completed":
                    raise HTTPException(409, {"message": "该请求已处理，不能自动重试；请核对状态", "turn_id": old["id"], "status": state["status"]})
                async def replay():
                    yield sse({"type": "turn_started", "turn_id": old["id"], "replayed": True})
                    yield sse({"type": "text_delta", "text": state["answer"]})
                    yield sse({"type": "turn_completed", "turn_id": old["id"], "replayed": True})
                return StreamingResponse(replay(), media_type="text/event-stream")
            task = asyncio.create_task(execute_turn(repo, settings, user["id"], session, turn_id, question, body.use_cache, queue, log))
            running[turn_id] = (task,user["id"],session)
            task.add_done_callback(lambda done: running.pop(turn_id, None))

        async def stream():
            try:
                yield sse({"type": "turn_started", "turn_id": turn_id, "run_id": log.run_id})
                while not task.done() or not queue.empty():
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), .5)
                        yield sse(event)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                if task.cancelled():
                    yield sse({"type": "cancelled", "turn_id": turn_id})
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})

    @app.get("/")
    async def index():
        return FileResponse(WEB / "index.html")

    app.mount("/web", StaticFiles(directory=WEB, check_dir=False), name="web")
    return app


app = create_app()
