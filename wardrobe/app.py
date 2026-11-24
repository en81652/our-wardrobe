import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, model_validator

from .cards import decode_photo, render_card
from .config import BASE, Identifier, StrictModel, load_settings

Name = Annotated[str, Field(min_length=1, max_length=60)]
Note = Annotated[str, Field(max_length=500)]
EncodedImage = Annotated[str, Field(max_length=7_000_000)]


class ItemInput(StrictModel):
    name: Name
    owner: Identifier
    category: Identifier
    added_by: Identifier
    description: Note = ""
    image_base64: EncodedImage | None = None


class ItemPatch(StrictModel):
    name: Name | None = None
    owner: Identifier | None = None
    category: Identifier | None = None
    description: Note | None = None
    image_base64: EncodedImage | None = None
    remove_image: bool = False
    use_count: Annotated[int, Field(ge=0)] | None = None
    last_used_at: datetime | None = None

    @model_validator(mode="after")
    def valid_changes(self):
        if any(getattr(self, key) is None for key in self.model_fields_set - {"image_base64", "last_used_at"}):
            raise ValueError("编辑字段不能为 null")
        if self.remove_image and self.image_base64 is not None:
            raise ValueError("不能同时上传和移除图片")
        return self


class NoteInput(StrictModel):
    author: Identifier
    text: Annotated[str, Field(min_length=1, max_length=500)]


class NoteDelete(StrictModel):
    author: Identifier
    confirm: bool = False


class ReadInput(StrictModel):
    record_ids: list[str] = Field(min_length=1, max_length=100)


class SelectionInput(StrictModel):
    chosen_by: Identifier
    target: Identifier
    line: Annotated[str, Field(max_length=40)] = ""


class DrawInput(SelectionInput):
    mode: Literal["outfit", "single"] = "outfit"
    category: Identifier | None = None
    categories: list[Identifier] | None = Field(default=None, min_length=1, max_length=40)
    counts: dict[Identifier, Annotated[int, Field(ge=1, le=8)]] = Field(default_factory=dict)
    item_ids: list[str] | None = Field(default=None, min_length=1, max_length=500)
    count: int = Field(default=1, ge=1, le=8)


class PickInput(SelectionInput):
    item_ids: list[str] = Field(min_length=1, max_length=8)


def now():
    return datetime.now(timezone.utc).isoformat()


def create_app():
    secret = os.environ.get("WARDROBE_API_KEY", "").strip()
    if not secret:
        raise RuntimeError("请先设置 WARDROBE_API_KEY；服务没有默认密钥")
    settings = load_settings()
    mcp_key = os.environ.get("WARDROBE_MCP_KEY", "").strip()
    if mcp_key and (not re.fullmatch(r"[A-Za-z0-9_-]{32,}", mcp_key) or mcp_key == secret):
        raise RuntimeError("WARDROBE_MCP_KEY 必须是独立的至少 32 位 URL 安全随机密钥，不能与网页密钥相同")
    directory = Path(os.environ.get("WARDROBE_DATA_DIR", str(BASE / "data"))).expanduser().resolve()
    media = directory / "uploads"
    media.mkdir(parents=True, exist_ok=True)
    database = directory / "wardrobe.sqlite3"
    roles = {role.id: role.name for role in settings.roles}
    categories = {category.id: category for category in settings.categories}

    @contextmanager
    def db():
        connection = sqlite3.connect(database, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL,
                category TEXT NOT NULL, added_by TEXT NOT NULL,
                description TEXT NOT NULL, image_file TEXT,
                created_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
                use_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES items(id),
                author TEXT NOT NULL, author_name TEXT NOT NULL,
                text TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS history (
                id TEXT PRIMARY KEY, target TEXT NOT NULL, created_at TEXT NOT NULL,
                record TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS read_receipts (
                record_id TEXT PRIMARY KEY REFERENCES history(id), read_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS notes_item ON notes(item_id, created_at);
            CREATE INDEX IF NOT EXISTS history_time ON history(created_at);
        """)

        # Extend databases created by the first release without discarding their contents.
        if "last_used_at" not in {row[1] for row in conn.execute("PRAGMA table_info(items)")}:
            conn.execute("ALTER TABLE items ADD COLUMN last_used_at TEXT")
        if "updated_at" not in {row[1] for row in conn.execute("PRAGMA table_info(notes)")}:
            conn.execute("ALTER TABLE notes ADD COLUMN updated_at TEXT")

    def auth(authorization: Annotated[str | None, Header()] = None):
        provided = (authorization or "").removeprefix("Bearer ")
        if not authorization or not authorization.startswith("Bearer ") or not hmac.compare_digest(provided.encode(), secret.encode()):
            raise HTTPException(401, "访问密钥无效，请重新输入", headers={"WWW-Authenticate": "Bearer"})

    def role_check(role):
        if role not in roles:
            raise HTTPException(422, "角色不存在，请先读取配置")

    def category_check(category, owner):
        role_check(owner)
        if category not in categories:
            raise HTTPException(422, "分类不存在，请先读取配置")
        if owner not in categories[category].owners:
            raise HTTPException(422, "该角色不能拥有这个分类的物品")

    def validate_content(category, description, has_image):
        if categories[category].text_only:
            if not description.strip():
                raise HTTPException(422, "指令必须填写正文")
            if len(description) > 200:
                raise HTTPException(422, "指令正文最多 200 字")
            if has_image:
                raise HTTPException(422, "指令不接受图片，请移除图片")

    def enabled(item):
        category = categories.get(item["category"])
        return bool(category and item["owner"] in roles and item["owner"] in category.owners)

    def media_url(filename):
        return f'{settings.public_base_url.rstrip("/")}/api/media/{filename}' if filename else None

    def item_json(row):
        item = dict(row)
        item["image_url"] = media_url(item.get("image_file"))
        item["enabled"] = enabled(item)
        category = categories.get(item["category"])
        item["category_name"] = category.name if category else item["category"]
        item["owner_name"] = roles.get(item["owner"], item["owner"])
        return item

    def get_item(conn, item_id):
        row = conn.execute("SELECT * FROM items WHERE id=? AND archived=0", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "物品不存在或已移除")
        return row

    def save_photo(encoded):
        if encoded is None:
            return None
        content = decode_photo(encoded)
        filename = uuid4().hex + ".jpg"
        (media / filename).write_bytes(content)
        return filename

    remote = None

    @asynccontextmanager
    async def lifespan(app):
        if remote is None:
            yield
        else:
            async with remote.session_manager.run():
                yield

    app = FastAPI(title=settings.title, version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith(("/api/", "/mcp")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return FileResponse(BASE / "static" / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    api = APIRouter(prefix="/api", dependencies=[Depends(auth)])

    @api.get("/config")
    def config():
        return settings.model_dump(exclude={"font_path", "webhook_url", "public_base_url", "notify_webhook_url"})

    @api.get("/link")
    def link():
        return {"label": "打开衣柜", "url": settings.public_base_url.rstrip("/") + "/"}

    @api.get("/openapi.json")
    def schema():
        return app.openapi()

    @api.get("/media/{filename}")
    def image(filename: str):
        if len(filename) != 36 or filename[-4:] not in (".jpg", ".png") or any(char not in "0123456789abcdef" for char in filename[:-4]):
            raise HTTPException(404, "图片不存在")
        path = media / filename
        if not path.is_file():
            raise HTTPException(404, "图片不存在")
        return FileResponse(path)

    @api.get("/items")
    def list_items(owner: str | None = None, category: str | None = None):
        with db() as conn:
            rows = conn.execute("SELECT * FROM items WHERE archived=0 ORDER BY created_at DESC").fetchall()
        return {"items": [item_json(row) for row in rows if (owner is None or row["owner"] == owner) and (category is None or row["category"] == category)]}

    @api.post("/items", status_code=201)
    def add_item(body: ItemInput):
        category_check(body.category, body.owner)
        role_check(body.added_by)
        validate_content(body.category, body.description, body.image_base64 is not None)
        filename = save_photo(body.image_base64)
        item_id = uuid4().hex
        try:
            with db() as conn:
                conn.execute("INSERT INTO items (id,name,owner,category,added_by,description,image_file,created_at) VALUES (?,?,?,?,?,?,?,?)",
                             (item_id, body.name, body.owner, body.category, body.added_by, body.description, filename, now()))
                result = item_json(get_item(conn, item_id))
        except Exception:
            if filename:
                (media / filename).unlink(missing_ok=True)
            raise
        return result

    @api.get("/items/{item_id}")
    def detail(item_id: str):
        with db() as conn:
            result = item_json(get_item(conn, item_id))
            result["uses"] = [json.loads(row["record"]) for row in conn.execute("SELECT record FROM history ORDER BY created_at DESC") if any(item["id"] == item_id for item in json.loads(row["record"])["items"])][:20]
            result["notes"] = [dict(row) for row in conn.execute("SELECT * FROM notes WHERE item_id=? ORDER BY created_at", (item_id,))]
        return result

    @api.patch("/items/{item_id}")
    def edit_item(item_id: str, body: ItemPatch):
        filename = None
        try:
            with db() as conn:
                old = dict(get_item(conn, item_id))
                changes = body.model_dump(mode="json", exclude_unset=True, exclude={"image_base64", "remove_image"})
                merged = old | changes
                category_check(merged["category"], merged["owner"])
                validate_content(merged["category"], merged["description"], body.image_base64 is not None or (bool(old["image_file"]) and not body.remove_image))
                if body.image_base64 is not None:
                    filename = save_photo(body.image_base64)
                    changes["image_file"] = filename
                elif body.remove_image:
                    changes["image_file"] = None
                if changes:
                    conn.execute("UPDATE items SET " + ",".join(key + "=?" for key in changes) + " WHERE id=?", [*changes.values(), item_id])
                result = item_json(get_item(conn, item_id))
        except Exception:
            if filename:
                (media / filename).unlink(missing_ok=True)
            raise
        # Old pictures remain available to historical snapshots.
        return result

    @api.delete("/items/{item_id}")
    def remove_item(item_id: str):
        with db() as conn:
            get_item(conn, item_id)
            conn.execute("UPDATE items SET archived=1 WHERE id=?", (item_id,))
        return {"removed": item_id}

    @api.post("/items/{item_id}/notes", status_code=201)
    def add_note(item_id: str, body: NoteInput):
        role_check(body.author)
        note = {"id": uuid4().hex, "item_id": item_id, "author": body.author, "author_name": roles[body.author], "text": body.text, "created_at": now()}
        with db() as conn:
            get_item(conn, item_id)
            conn.execute("INSERT INTO notes (id,item_id,author,author_name,text,created_at) VALUES (:id,:item_id,:author,:author_name,:text,:created_at)", note)
        return note

    @api.patch("/items/{item_id}/notes/{note_id}")
    def edit_note(item_id: str, note_id: str, body: NoteInput):
        role_check(body.author)
        with db() as conn:
            get_item(conn, item_id)
            row = conn.execute("SELECT * FROM notes WHERE id=? AND item_id=?", (note_id, item_id)).fetchone()
            if not row:
                raise HTTPException(404, "批注不存在")
            if row["author"] != body.author:
                raise HTTPException(403, "只能修改自己写的批注")
            conn.execute("UPDATE notes SET text=?,updated_at=? WHERE id=?", (body.text, now(), note_id))
            return dict(conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone())

    @api.delete("/items/{item_id}/notes/{note_id}")
    def delete_note(item_id: str, note_id: str, body: NoteDelete):
        role_check(body.author)
        if not body.confirm:
            raise HTTPException(422, "请确认删除这条批注")
        with db() as conn:
            get_item(conn, item_id)
            row = conn.execute("SELECT * FROM notes WHERE id=? AND item_id=?", (note_id, item_id)).fetchone()
            if not row:
                raise HTTPException(404, "批注不存在")
            if row["author"] != body.author:
                raise HTTPException(403, "只能删除自己写的批注")
            conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
        return {"removed": note_id}

    def complete_selection(body, mode):
        role_check(body.chosen_by)
        role_check(body.target)
        card_file = None
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                skipped = []
                if mode == "pick":
                    if len(body.item_ids) != len(set(body.item_ids)):
                        raise HTTPException(422, "不能重复选择同一件物品")
                    items = [dict(get_item(conn, item_id)) for item_id in body.item_ids]
                    if any(item["owner"] != body.target or not enabled(item) for item in items):
                        raise HTTPException(422, "所选物品必须属于目标角色且分类可用")
                else:
                    if body.item_ids is not None:
                        if body.category or body.categories or body.counts or body.mode != "outfit":
                            raise HTTPException(422, "候选池请只传 item_ids 和 count")
                        if len(body.item_ids) != len(set(body.item_ids)):
                            raise HTTPException(422, "候选池不能重复")
                        pool = [dict(get_item(conn, item_id)) for item_id in body.item_ids]
                        if any(item["owner"] != body.target or not enabled(item) for item in pool):
                            raise HTTPException(422, "候选物品必须属于目标角色且分类可用")
                        if body.count > len(pool):
                            raise HTTPException(422, "抽取数量不能超过候选数量")
                        items = secrets.SystemRandom().sample(pool, body.count)
                    else:
                        if body.count != 1:
                            raise HTTPException(422, "按格抽取请使用 counts")
                        if body.categories is not None:
                            if body.category or body.mode != "outfit":
                                raise HTTPException(422, "勾格抽取不能同时指定单抽分类")
                            if len(body.categories) != len(set(body.categories)):
                                raise HTTPException(422, "不能重复选择分类")
                            for key in body.categories:
                                category_check(key, body.target)
                            selected_categories = [categories[key] for key in body.categories]
                        elif body.mode == "single":
                            if body.category is None:
                                raise HTTPException(422, "单抽需要指定 category")
                            category_check(body.category, body.target)
                            selected_categories = [categories[body.category]]
                        else:
                            if body.category is not None:
                                raise HTTPException(422, "抽一套不接受 category，请使用 single")
                            selected_categories = [cat for cat in settings.categories if body.target in cat.owners and
                                                   (cat.in_outfit is True or isinstance(cat.in_outfit, list) and body.target in cat.in_outfit)]
                        if set(body.counts) - {cat.id for cat in selected_categories}:
                            raise HTTPException(422, "counts 只能指定本次参与的分类")
                        items = []
                        mixed = body.categories is not None and len(selected_categories) > 1
                        for category in selected_categories:
                            count = body.counts.get(category.id, 1)
                            if count > category.max_count or (mixed and count != 1):
                                raise HTTPException(422, "数量超过分类上限；混抽时每格只能 1 件")
                            pool = conn.execute("SELECT * FROM items WHERE owner=? AND category=? AND archived=0", (body.target, category.id)).fetchall()
                            if pool:
                                items.extend(dict(item) for item in secrets.SystemRandom().sample(pool, min(count, len(pool))))
                            else:
                                skipped.append(category.id)
                if len(items) > 8:
                    raise HTTPException(422, "一张卡片最多八件，请减少格子或数量")
                if not items:
                    raise HTTPException(409, "没有可抽取的物品，请先添加到对应角色和分类")
                snapshots = [item_json(item) | {"action": categories[item["category"]].action, "text_only": categories[item["category"]].text_only} for item in items]
                text = f'{roles[body.chosen_by]} 为 {roles[body.target]}{"抽到" if mode == "draw" else "挑选"}：' + "；".join(f'{item["action"]}{item["name"]}' + (f'（{item["description"]}）' if item["text_only"] else "") for item in snapshots)
                if body.line:
                    text += "。" + body.line
                wardrobe_url = settings.public_base_url.rstrip("/") + "/"
                text += "\n打开衣柜：" + wardrobe_url
                record = {"id": uuid4().hex, "mode": mode, "chosen_by": body.chosen_by,
                          "chosen_by_name": roles[body.chosen_by], "target": body.target,
                          "target_name": roles[body.target], "items": snapshots, "line": body.line,
                          "text": text, "wardrobe_url": wardrobe_url, "created_at": now(), "skipped_categories": skipped,
                          "webhook": {"status": "pending" if settings.webhook_url else "disabled"},
                          "notification": {"status": ("pending" if settings.notify_webhook_url else "disabled") if body.chosen_by == settings.clients.web else "not_applicable"}}
                card_file = uuid4().hex + ".png"
                (media / card_file).write_bytes(render_card(record, media, settings.font_path))
                record["card_url"] = media_url(card_file)
                conn.execute("INSERT INTO history VALUES (?,?,?,?)", (record["id"], body.target, record["created_at"], json.dumps(record, ensure_ascii=False)))
                conn.executemany("UPDATE items SET use_count=use_count+1,last_used_at=? WHERE id=?", [(record["created_at"], item["id"]) for item in items])
        except Exception:
            if card_file:
                (media / card_file).unlink(missing_ok=True)
            raise
        # Persist the outfit first: delivery failure must never roll it back.
        hooks = [("webhook", settings.webhook_url, "wardrobe.selection")]
        if body.chosen_by == settings.clients.web:
            hooks.append(("notification", settings.notify_webhook_url, "wardrobe.notify"))
        for key, url, event in hooks:
            if not url:
                continue
            try:
                response = httpx.post(url, json={"event": event, **record}, timeout=5, follow_redirects=False)
                record[key] = {"status": "delivered" if 200 <= response.status_code < 300 else "failed", "http_status": response.status_code}
            except httpx.HTTPError:
                record[key] = {"status": "unknown", "detail": "连接失败或超时，请检查接收端；不会自动重发"}
            with db() as conn:
                conn.execute("UPDATE history SET record=? WHERE id=?", (json.dumps(record, ensure_ascii=False), record["id"]))
        return record

    @api.post("/draw", status_code=201)
    def draw(body: DrawInput):
        return complete_selection(body, "draw")

    @api.post("/pick", status_code=201)
    def pick(body: PickInput):
        return complete_selection(body, "pick")

    @api.get("/history")
    def history(target: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20,
                offset: Annotated[int, Query(ge=0)] = 0):
        with db() as conn:
            rows = conn.execute("SELECT record FROM history WHERE (? IS NULL OR target=?) ORDER BY created_at DESC LIMIT ? OFFSET ?", (target, target, limit, offset)).fetchall()
        return {"history": [json.loads(row["record"]) for row in rows]}

    @api.get("/unread")
    def unread(limit: Annotated[int, Query(ge=1, le=100)] = 20):
        with db() as conn:
            rows = conn.execute("SELECT h.record FROM history h LEFT JOIN read_receipts r ON h.id=r.record_id WHERE r.record_id IS NULL ORDER BY h.created_at").fetchall()
        records = [json.loads(row["record"]) for row in rows if json.loads(row["record"])["chosen_by"] == settings.clients.web]
        return {"history": records[:limit], "remaining": max(0, len(records) - limit)}

    @api.post("/unread/read")
    def mark_read(body: ReadInput):
        timestamp = now()
        with db() as conn:
            for record_id in body.record_ids:
                row = conn.execute("SELECT record FROM history WHERE id=?", (record_id,)).fetchone()
                if not row or json.loads(row["record"])["chosen_by"] != settings.clients.web:
                    raise HTTPException(422, "只能标记人发起的现有抽卡")
                conn.execute("INSERT OR IGNORE INTO read_receipts VALUES (?,?)", (record_id, timestamp))
        return {"read": body.record_ids, "read_at": timestamp}

    app.include_router(api)
    if mcp_key:
        from .remote import mount_mcp
        remote = mount_mcp(app, mcp_key, secret, settings.public_base_url, directory)
    return app
