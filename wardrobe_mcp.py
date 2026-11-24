"""Standalone stdio MCP adapter. All wardrobe state lives in the HTTP service."""
import base64
import json
import os
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import httpx
from mcp.server.fastmcp import FastMCP, Image

mcp = FastMCP("our-wardrobe")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
adapters = ContextVar("wardrobe_adapters", default=None)
tool_functions = []


def tool(function):
    tool_functions.append(function)
    return mcp.tool()(function)


def request(path: str, method: str = "GET", payload=None, binary=False):
    if adapters.get() is not None:
        return adapters.get()[0](path, method, payload, binary)
    base = os.environ.get("WARDROBE_URL", "http://127.0.0.1:8765").rstrip("/")
    secret = os.environ.get("WARDROBE_API_KEY", "").strip()
    if not secret:
        raise ValueError("请设置 WARDROBE_API_KEY，与 HTTP 服务一致")
    try:
        response = httpx.request(method, base + "/api" + path, json=payload,
                                 headers={"Authorization": "Bearer " + secret}, timeout=30,
                                 follow_redirects=False)
    except httpx.HTTPError as exc:
        raise ValueError("衣柜连接失败或超时。写入可能已经完成，请先查列表或历史再决定是否重试。") from exc
    if not 200 <= response.status_code < 300:
        try:
            detail = response.json().get("detail", "请求失败")
        except ValueError:
            detail = "服务未返回 JSON，请检查 WARDROBE_URL"
        raise ValueError(f"衣柜请求失败 ({response.status_code}): {detail}")
    return response.content if binary else response.json()


def actor(value):
    return value if value is not None else request("/config")["clients"]["mcp"]


def photo(path):
    if not path:
        return None
    if adapters.get() is not None:
        path = adapters.get()[1](path)
    with Path(path).expanduser().open("rb") as stream:
        content = stream.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片不能超过 5 MB")
    return base64.b64encode(content).decode("ascii")


def item_path(item_id):
    return "/items/" + quote(item_id, safe="")


@tool
def wardrobe_config() -> dict:
    """先读取角色 id、分类 id、可拥有角色和抽一套规则；不要猜测或写死角色与分类。"""
    return request("/config")


@tool
def wardrobe_link() -> dict:
    """取得“打开衣柜”的网页入口，可发给人；地址不包含任何访问密钥。"""
    return request("/link")


@tool
def wardrobe_list(owner: str | None = None, category: str | None = None) -> dict:
    """查看衣柜，可按所有者/分类筛选。列表只含图片地址；看图使用 wardrobe_view。"""
    query = urlencode({key: value for key, value in {"owner": owner, "category": category}.items() if value is not None})
    return request("/items?" + query)


@tool
def wardrobe_view(item_id: str) -> list:
    """读取物品详情、双方备注与使用次数；存在图片时同时返回图片本身。"""
    item = request(item_path(item_id))
    result = [json.dumps(item, ensure_ascii=False)]
    if item.get("image_url"):
        path = urlsplit(item["image_url"]).path
        if not path.startswith("/api/media/") or "/" in path[len("/api/media/"):]:
            raise ValueError("服务返回了无效的图片路径")
        result.append(Image(data=request(path.removeprefix("/api"), binary=True), format="jpeg"))
    return result


@tool
def wardrobe_add(name: str, owner: str, category: str, description: str = "",
                 image_path: str = "", added_by: str | None = None) -> dict:
    """添加物品，可上传 MCP 所在机器上的本地图片，最大 5 MB；发起人默认取 clients.mcp。"""
    return request("/items", "POST", {"name": name, "owner": owner, "category": category,
                   "description": description, "added_by": actor(added_by), "image_base64": photo(image_path)})


@tool
def wardrobe_edit(item_id: str, name: str | None = None, owner: str | None = None,
                  category: str | None = None, description: str | None = None,
                  image_path: str | None = None, remove_image: bool = False,
                  use_count: int | None = None, last_used_at: str | None = None,
                  clear_last_used_at: bool = False) -> dict:
    """编辑名称、所有者、分类、描述或图片；description='' 清空描述，remove_image=true 移除图片。"""
    payload = {key: value for key, value in {"name": name, "owner": owner, "category": category,
               "description": description, "use_count": use_count, "last_used_at": last_used_at}.items() if value is not None}
    if clear_last_used_at:
        payload["last_used_at"] = None
    if image_path:
        payload["image_base64"] = photo(image_path)
    if remove_image:
        payload["remove_image"] = True
    return request(item_path(item_id), "PATCH", payload)


@tool
def wardrobe_remove(item_id: str) -> dict:
    """从衣柜移除物品；保留其过去的穿搭记录。"""
    return request(item_path(item_id), "DELETE")


@tool
def wardrobe_note(item_id: str, text: str, author: str | None = None) -> dict:
    """写一条 1–500 字批注，保留作者与时间；author 默认取 clients.mcp。"""
    return request(item_path(item_id) + "/notes", "POST", {"text": text, "author": actor(author)})


@tool
def wardrobe_note_edit(item_id: str, note_id: str, text: str, author: str | None = None) -> dict:
    """修改自己写的批注，保留创建时间并记录修改时间。"""
    return request(item_path(item_id) + "/notes/" + quote(note_id, safe=""), "PATCH",
                   {"author": actor(author), "text": text})


@tool
def wardrobe_note_delete(item_id: str, note_id: str, confirm: bool = False, author: str | None = None) -> dict:
    """删除自己写的批注。先向用户确认，确认后传 confirm=true。"""
    if not confirm:
        raise ValueError("删除前请确认具体批注，再传 confirm=true")
    return request(item_path(item_id) + "/notes/" + quote(note_id, safe=""), "DELETE",
                   {"author": actor(author), "confirm": True})


@tool
def wardrobe_draw(target: str, mode: str = "outfit", category: str | None = None,
                  line: str = "", chosen_by: str | None = None,
                  categories: list[str] | None = None, counts: dict[str, int] | None = None,
                  item_ids: list[str] | None = None, count: int = 1) -> dict:
    """抽一套；single+category 单抽；categories 勾格混抽每格一件。
    套装/单格可传 counts={分类id:件数}，上限见配置，玩具默认3。
    候选池传 item_ids+count，不与分类参数混用；最多八件，附一句话最多40字。
    返回卡片和两个钩子状态；超时先查历史。
    """
    return request("/draw", "POST", {"target": target, "mode": mode, "category": category,
                   "line": line, "chosen_by": actor(chosen_by), "categories": categories,
                   "counts": counts or {}, "item_ids": item_ids, "count": count})


@tool
def wardrobe_unread(limit: int = 20) -> dict:
    """查人发起的未读抽挑（包括人给自己抽的）。返回完整物品快照与指令正文。
    先读本次结果、按需 wardrobe_card 看图，再用 wardrobe_mark_read 确认实际看过的 id。
    不因查询或 webhook 成功就自动标记，避免漏读。
    """
    return request("/unread?" + urlencode({"limit": limit}))


@tool
def wardrobe_mark_read(record_ids: list[str]) -> dict:
    """看完未读抽卡后，标记实际读过的记录 id；不影响之后新来的抽卡。"""
    return request("/unread/read", "POST", {"record_ids": record_ids})


@tool
def wardrobe_pick(target: str, item_ids: list[str], line: str = "", chosen_by: str | None = None) -> dict:
    """为目标手选 1–8 件不同物品，须全部属于目标。生成卡片并触发已配置的 webhook；超时先查历史。"""
    return request("/pick", "POST", {"target": target, "item_ids": item_ids, "line": line,
                   "chosen_by": actor(chosen_by)})


@tool
def wardrobe_history(target: str | None = None, limit: int = 20, offset: int = 0) -> dict:
    """分页查看抽挑历史及当时的物品快照、卡片地址、通知结果。pending/unknown 时先检查接收端，不要盲目重抽。"""
    values = {"limit": limit, "offset": offset}
    if target is not None:
        values["target"] = target
    return request("/history?" + urlencode(values))


@tool
def wardrobe_card(record_id: str) -> list:
    """查看某条穿搭记录的卡片图片。先从历史中获取 record_id。"""
    # History is paginated to avoid silently limiting lookups to recent records.
    offset = 0
    while True:
        records = request("/history?" + urlencode({"limit": 100, "offset": offset}))["history"]
        for record in records:
            if record["id"] == record_id:
                path = urlsplit(record["card_url"]).path
                if not path.startswith("/api/media/") or "/" in path[len("/api/media/"):]:
                    raise ValueError("服务返回了无效的卡片路径")
                return [record["text"], Image(data=request(path.removeprefix("/api"), binary=True), format="png")]
        if len(records) < 100:
            raise ValueError("未找到这条穿搭记录")
        offset += 100


if __name__ == "__main__":
    mcp.run(transport="stdio")
