import argparse

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="启动共享衣柜")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    # A remote MCP URL contains a credential. Do not write request paths to logs.
    uvicorn.run("wardrobe.app:create_app", factory=True, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
