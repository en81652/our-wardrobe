import json
import os
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

BASE = Path(__file__).resolve().parent.parent
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]
Label = Annotated[str, Field(min_length=1, max_length=60)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Role(StrictModel):
    id: Identifier
    name: Label


class Category(StrictModel):
    id: Identifier
    name: Label
    owners: list[Identifier] = Field(min_length=1)
    action: Annotated[str, Field(min_length=1, max_length=20)]
    in_outfit: bool | list[Identifier]
    max_count: int = Field(default=1, ge=1, le=8)
    text_only: bool = False


class Clients(StrictModel):
    web: Identifier
    mcp: Identifier


class Settings(StrictModel):
    title: Label
    roles: list[Role] = Field(min_length=2, max_length=2)
    clients: Clients
    categories: list[Category] = Field(max_length=40)
    font_path: str = ""
    public_base_url: str = "http://127.0.0.1:8765"
    webhook_url: str = ""
    notify_webhook_url: str = ""

    @model_validator(mode="after")
    def valid_references(self):
        roles = {r.id for r in self.roles}
        if len(roles) != len(self.roles):
            raise ValueError("角色 id 不能重复")
        if len({c.id for c in self.categories}) != len(self.categories):
            raise ValueError("分类 id 不能重复")
        if {self.clients.web, self.clients.mcp} - roles:
            raise ValueError("clients 必须引用现有角色")
        if self.clients.web == self.clients.mcp:
            raise ValueError("网页与 MCP 默认角色必须不同")
        if any(isinstance(c.in_outfit, list) and set(c.in_outfit) - set(c.owners) for c in self.categories):
            raise ValueError("套装角色必须属于分类 owners")
        if any(set(c.owners) - roles for c in self.categories):
            raise ValueError("分类 owners 必须引用现有角色")
        for value in (self.public_base_url, self.webhook_url, self.notify_webhook_url):
            if value:
                url = urlsplit(value)
                if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password or url.fragment:
                    raise ValueError("地址必须是无内嵌账号的 HTTP(S) URL")
        base = urlsplit(self.public_base_url)
        if not base.netloc:
            raise ValueError("public_base_url / PUBLIC_URL 不能为空")
        if base.path not in ("", "/") or base.query:
            raise ValueError("public_base_url 仅支持 origin，不含子路径或查询参数")
        return self


def load_settings():
    default = BASE / "config.local.json"
    path = Path(os.environ.get("WARDROBE_CONFIG", str(default if default.exists() else BASE / "config.json"))).expanduser().resolve()
    values = json.loads(path.read_text(encoding="utf-8"))
    if "PUBLIC_URL" in os.environ:
        values["public_base_url"] = os.environ["PUBLIC_URL"].strip()
    settings = Settings.model_validate(values)
    if settings.font_path:
        font = Path(settings.font_path).expanduser()
        settings.font_path = str(font if font.is_absolute() else path.parent / font)
    return settings
