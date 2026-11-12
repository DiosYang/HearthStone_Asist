"""用户/会话隔离的流式问答；SQLite历史、预算摘要与精确缓存。"""
import argparse
import asyncio
from hearthstone_assistant.config import load_settings
from hearthstone_assistant.config import PROJECT_ROOT
from hearthstone_assistant.log import EventLog


def main():
    parser = argparse.ArgumentParser(description="炉石小助手：流式问答、SQLite会话和上下文管理")
    parser.add_argument("command", choices=["doctor", "chat", "sessions", "history"])
    parser.add_argument("--user", default="local", help="本机用户标识，不是身份认证")
    parser.add_argument("--session", help="继续指定会话；不指定时chat新建会话")
    parser.add_argument("--no-cache", action="store_true", help="跳过应用回答缓存，不读也不写")
    args = parser.parse_args()
    try:
        log = EventLog(PROJECT_ROOT / "data" / "logs", console=args.command == "doctor")
        log.emit("run_start")
    except OSError:
        parser.exit(1, "日志目录无法写入，请检查项目data/权限。\n")
    try:
        settings = load_settings()
    except (OSError, ValueError) as exc:
        log.emit("config_failed", error_type=type(exc).__name__)
        parser.exit(1, "配置检查失败：" + str(exc) + "\n")
    log.emit("config_checked", model=settings.model, key_configured=bool(settings.api_key))
    print("项目目录：", settings.project_root)
    print("配置文件：", settings.env_file, "（存在）" if settings.env_file.is_file() else "（不存在）")
    print("模型名称：", settings.model)
    print("模型地址：", settings.base_url)
    print("API Key：", "已配置（不显示内容，尚未验证有效性）" if settings.api_key else "未配置")
    if args.command == "doctor":
        print("本步骤没有发送网络请求，不消耗API额度。")
    print("日志文件：", log.path)
    if not settings.api_key and args.command in ("doctor", "chat"):
        log.emit("run_end", status="missing_key")
        parser.exit(1, "请在原课程.env配置Key，或在本项目.env中单独配置。\n")
    if args.command in ("chat", "sessions", "history"):
        from hearthstone_assistant.storage.sqlite import SessionStore
        store = SessionStore(PROJECT_ROOT / "data" / "assistant.sqlite3")
        try:
            store.ensure_user(args.user)
            if args.command == "sessions":
                for row in store.list(args.user):
                    print(row)
                log.emit("run_end", status="ok")
                return
            if args.command == "history":
                if not args.session:
                    raise ValueError("history需要--session")
                for turn in store.turns(args.user, args.session):
                    print("你>", turn["question"], "\n助手>", turn["answer"])
                log.emit("run_end", status="ok")
                return
            session = args.session or store.create(args.user)
            store.require(args.user, session)
            log.user_id, log.session_id = args.user, session
            print("用户：", args.user, "会话：", session)
            print("真实流式调用；可能另产生摘要费用。当前无工具/长期偏好。Ctrl+C取消。")
            question = input("你> ").strip()
            if not question:
                log.emit("run_end", status="empty_input")
                return
            asyncio.run(chat_once(settings, question, log, store, args.user, session, not args.no_cache))
        except (KeyboardInterrupt, EOFError):
            print("\n已取消；已显示的文字不是完整回复。")
            log.emit("run_end", status="cancelled")
            return
        except Exception as exc:
            # 不打印SDK异常对象，避免原始请求/认证信息泄漏。
            print("\n调用失败：", type(exc).__name__, "；部分文字不能当作完整结果。")
            log.emit("run_end", status="failed", error_type=type(exc).__name__)
            parser.exit(1)
        finally:
            store.close()
    log.emit("run_end", status="ok")


async def chat_once(settings, question, log, store, user, session, use_cache=True):
    from hearthstone_assistant.agents.run import run_agent
    from hearthstone_assistant.memory.context import prepare_context
    from hearthstone_assistant.cache.answers import request_key
    turns = store.turns(user, session)
    messages = await prepare_context(settings, store, user, session, turns, question, log)
    key = request_key(settings, messages)
    cached = store.cached_answer(user, session, key) if use_cache else None
    log.emit("answer_cache", status="hit" if cached is not None else "miss" if use_cache else "bypassed")
    if cached is not None:
        print("助手（15分钟内的相同上下文缓存，未重新请求模型）> ", cached)
        store.append(user, session, question, cached, expected_count=len(turns))
        log.emit("session_saved", status="ok")
        return
    print("助手> ", end="", flush=True)
    try:
        answer = await run_agent(settings, question, log, messages=messages,
                                 on_text=lambda text: print(text, end="", flush=True))
        if use_cache:
            store.cache_answer(user, session, key, answer)
        store.append(user, session, question, answer, expected_count=len(turns))
        log.emit("session_saved", status="ok")
    finally:
        print()


if __name__ == "__main__":
    main()
