"""Load optional neutral examples through the same authenticated HTTP API."""
import argparse
import json
import os
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description="导入示例物品，已存在的同名同角色同分类物品会跳过")
    parser.add_argument("--file", type=Path, default=Path(__file__).resolve().parents[1] / "examples" / "items.json")
    args = parser.parse_args()
    secret = os.environ.get("WARDROBE_API_KEY", "").strip()
    if not secret:
        parser.error("请先设置 WARDROBE_API_KEY")
    base = os.environ.get("WARDROBE_URL", "http://127.0.0.1:8765").rstrip("/")
    with httpx.Client(base_url=base, headers={"Authorization": "Bearer " + secret}, timeout=30) as client:
        response = client.get("/api/config"); response.raise_for_status()
        author = response.json()["clients"]["web"]
        response = client.get("/api/items"); response.raise_for_status()
        known = {(item["owner"], item["category"], item["name"]) for item in response.json()["items"]}
        count = 0
        for item in json.loads(args.file.read_text(encoding="utf-8")):
            identity = (item["owner"], item["category"], item["name"])
            if identity in known:
                continue
            response = client.post("/api/items", json={"added_by": author, **item})
            response.raise_for_status()
            known.add(identity)
            count += 1
        print(f"已添加 {count} 件示例物品。")


if __name__ == "__main__":
    main()
