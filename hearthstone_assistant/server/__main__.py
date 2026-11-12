"""本机网页服务入口：python -m hearthstone_assistant.server。"""
import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="炉边本机网页服务（单worker、仅本机访问）")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口须在1024—65535之间")
    uvicorn.run("hearthstone_assistant.server.app:app", host="127.0.0.1", port=args.port,
                workers=1, access_log=False)


if __name__ == "__main__":
    main()
