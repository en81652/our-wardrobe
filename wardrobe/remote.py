"""Streamable HTTP transport using the same tool functions as stdio."""
import hmac
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

import anyio
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from wardrobe_mcp import adapters, tool_functions


class KeyedEndpoint:
    def __init__(self, app, key):
        self.app, self.key = app, key

    async def __call__(self, scope, receive, send):
        path = scope["path"].removeprefix(scope.get("root_path", ""))
        provided = path.removeprefix("/").removesuffix("/")
        if not hmac.compare_digest(provided.encode(), self.key.encode()):
            await JSONResponse({"detail": "MCP 地址无效"}, status_code=404)(scope, receive, send)
            return
        if scope["method"] == "GET":
            # Stateless tools have no unsolicited events; clients may probe for SSE.
            await JSONResponse({"detail": "请使用 POST 调用 MCP"}, status_code=405,
                               headers={"Allow": "POST"})(scope, receive, send)
            return
        # Both /mcp/key and /mcp/key/ work without a credential-bearing redirect.
        scope = {**scope, "path": scope.get("root_path", "") + "/"}
        scope["raw_path"] = scope["path"].encode()
        await self.app(scope, receive, send)


def mount_mcp(app, key, api_key, public_url, directory):
    origin = urlsplit(public_url)
    # Tool workers await sync API workers; give the two stages separate capacity.
    tool_limiter = anyio.CapacityLimiter(8)
    server = FastMCP(
        "our-wardrobe", stateless_http=True, json_response=True, streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[origin.netloc, "127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=[public_url.rstrip("/"), "http://127.0.0.1:*", "http://localhost:*"],
        ),
    )

    async def send_request(path, method, payload, binary):
        # Calls stay inside this app; no public round trip, port assumption, or second server.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost",
                                     headers={"Authorization": "Bearer " + api_key}) as client:
            response = await client.request(method, "/api" + path, json=payload)
        if not 200 <= response.status_code < 300:
            raise ValueError(f"衣柜请求失败 ({response.status_code}): {response.json().get('detail', '请求失败')}")
        return response.content if binary else response.json()

    def request(path, method="GET", payload=None, binary=False):
        return anyio.from_thread.run(send_request, path, method, payload, binary)

    def imported_photo(path):
        imports = (directory / "mcp-imports").resolve()
        candidate = Path(path).expanduser()
        candidate = (candidate if candidate.is_absolute() else imports / candidate).resolve()
        if not candidate.is_relative_to(imports):
            raise ValueError("远程 image_path 只能读取数据目录下 mcp-imports 内的图片；请先由管理员放入图片")
        return candidate

    def register(function):
        @wraps(function)
        async def call(**kwargs):
            def run():
                token = adapters.set((request, imported_photo))
                try:
                    return function(**kwargs)
                finally:
                    adapters.reset(token)
            return await anyio.to_thread.run_sync(run, limiter=tool_limiter)
        server.add_tool(call)

    for function in tool_functions:
        register(function)
    app.mount("/mcp", KeyedEndpoint(server.streamable_http_app(), key))
    app.state.remote_mcp = server
    return server
