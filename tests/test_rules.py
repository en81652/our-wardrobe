import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from PIL import Image, ImageFont
from pydantic import ValidationError

from wardrobe.app import create_app
from wardrobe.cards import font_for
from wardrobe.config import BASE, Settings


class WardrobeRules(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
        self.directory = Path(self.temp.name)
        self.config_file = self.directory / "config.json"
        self.environment = patch.dict(os.environ, {"WARDROBE_API_KEY": "temporary-test-key", "WARDROBE_DATA_DIR": str(self.directory / "data"), "WARDROBE_CONFIG": str(self.config_file)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def client(self):
        self.config_file.write_text(json.dumps(self.config), encoding="utf-8")
        client_type = TestClient
        if os.environ.get("WARDROBE_TEST_DIRECT") == "1":
            from direct_client import DirectClient
            client_type = DirectClient
        client = client_type(create_app(), headers={"Authorization": "Bearer temporary-test-key"})
        self.addCleanup(client.close)
        return client

    def add(self, client, name="测试上衣", owner="human", category="clothes"):
        response = client.post("/api/items", json={"name": name, "owner": owner, "category": category, "added_by": owner})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_missing_key_fails_closed(self):
        with patch.dict(os.environ, {"WARDROBE_API_KEY": ""}):
            with self.assertRaises(RuntimeError):
                create_app()

    def test_complete_flow_and_identity(self):
        client = self.client()
        authorization = client.headers["Authorization"]
        client.headers["Authorization"] = "Bearer wrong-test-key"
        self.assertEqual(client.get("/api/items").status_code, 401)
        client.headers["Authorization"] = authorization
        first = self.add(client, "白衬衫")
        second = self.add(client, "白袜子", category="stockings")
        other = self.add(client, "针织衫", owner="ai")
        self.assertEqual(len(client.get("/api/items?owner=human").json()["items"]), 2)
        draw = client.post("/api/draw", json={"chosen_by": "human", "target": "human"})
        self.assertEqual(draw.status_code, 201)
        self.assertEqual(len(draw.json()["items"]), 2)
        pick = client.post("/api/pick", json={"chosen_by": "ai", "target": "human", "item_ids": [first["id"], second["id"]]})
        self.assertEqual(pick.status_code, 201)
        self.assertEqual(pick.json()["chosen_by"], "ai")
        self.assertEqual(pick.json()["target"], "human")
        card = client.get(pick.json()["card_url"])
        self.assertEqual(Image.open(io.BytesIO(card.content)).format, "PNG")
        note = client.post(f'/api/items/{first["id"]}/notes', json={"author": "ai", "text": "很适合今天"})
        self.assertEqual(note.status_code, 201)
        item = client.get(f'/api/items/{first["id"]}').json()
        self.assertEqual(item["notes"][0]["author"], "ai")
        self.assertEqual(item["use_count"], 2)
        history = client.get("/api/history?target=human").json()["history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["id"], pick.json()["id"])
        for ids in ([first["id"], first["id"]], [first["id"], other["id"]]):
            self.assertEqual(client.post("/api/pick", json={"chosen_by": "ai", "target": "human", "item_ids": ids}).status_code, 422)
        client.patch(f'/api/items/{first["id"]}', json={"name": "改名后"})
        client.delete(f'/api/items/{first["id"]}')
        self.assertEqual(client.get(f'/api/items/{first["id"]}').status_code, 404)
        self.assertEqual(client.get("/api/history").json()["history"][0]["items"][0]["name"], "白衬衫")
        self.assertEqual(client.get(pick.json()["card_url"]).status_code, 200)

    def test_config_rejects_invalid_references(self):
        self.config["categories"][0]["owners"] = ["missing"]
        with self.assertRaises(ValidationError):
            Settings.model_validate(self.config)

    def test_custom_roles_categories_actions_and_eligibility(self):
        self.config["roles"] = [{"id": "person", "name": "朋友"}, {"id": "companion", "name": "伙伴"}]
        self.config["clients"] = {"web": "person", "mcp": "companion"}
        self.config["categories"] = [
            {"id": "hats", "name": "帽子", "owners": ["person"], "action": "戴上", "in_outfit": True},
            {"id": "bags", "name": "包", "owners": ["person", "companion"], "action": "背上", "in_outfit": False},
        ]
        client = self.client()
        self.add(client, "遮阳帽", "person", "hats")
        self.add(client, "帆布包", "person", "bags")
        bad = client.post("/api/items", json={"name": "帽子", "owner": "companion", "category": "hats", "added_by": "person"})
        self.assertEqual(bad.status_code, 422)
        record = client.post("/api/draw", json={"chosen_by": "companion", "target": "person"}).json()
        self.assertEqual(len(record["items"]), 1)
        self.assertIn("伙伴 为 朋友", record["text"])
        self.assertIn("戴上遮阳帽", record["text"])
        single = client.post("/api/draw", json={"chosen_by": "person", "target": "person", "mode": "single", "category": "bags"}).json()
        self.assertIn("背上帆布包", single["text"])

    def test_removed_category_keeps_items_and_history(self):
        client = self.client()
        item = self.add(client)
        first = client.post("/api/draw", json={"chosen_by": "ai", "target": "human"}).json()
        self.config["categories"] = []
        restarted = self.client()
        self.assertFalse(restarted.get("/api/items").json()["items"][0]["enabled"])
        self.assertEqual(restarted.post("/api/draw", json={"chosen_by": "ai", "target": "human"}).status_code, 409)
        self.assertEqual(restarted.post("/api/pick", json={"chosen_by": "ai", "target": "human", "item_ids": [item["id"]]}).status_code, 422)
        self.assertEqual(restarted.get("/api/history").json()["history"][0]["text"], first["text"])

    def test_webhook_success_failure_and_timeout_keep_record(self):
        self.config["webhook_url"] = "https://hooks.example.org/wardrobe"
        client = self.client()
        self.add(client)
        for value, expected in [(httpx.Response(204), "delivered"), (httpx.Response(500), "failed"), (httpx.ReadTimeout("test"), "unknown")]:
            with self.subTest(status=expected):
                kwargs = {"side_effect": value} if isinstance(value, Exception) else {"return_value": value}
                with patch("wardrobe.app.httpx.post", **kwargs) as send:
                    response = client.post("/api/draw", json={"chosen_by": "ai", "target": "human"})
                self.assertEqual(response.status_code, 201)
                record = response.json()
                self.assertEqual(record["webhook"]["status"], expected)
                payload = send.call_args.kwargs["json"]
                self.assertIn("card_url", payload)
                self.assertEqual(payload["event"], "wardrobe.selection")
                self.assertNotIn("headers", send.call_args.kwargs)
                self.assertEqual(client.get("/api/history").json()["history"][0]["webhook"]["status"], expected)
        self.assertEqual(len(client.get("/api/history").json()["history"]), 3)

    def test_image_replace_remove_and_invalid_patch(self):
        client = self.client()
        item = self.add(client)
        output = io.BytesIO(); Image.new("RGB", (20, 20)).save(output, "PNG")
        encoded = base64.b64encode(output.getvalue()).decode()
        path = "/api/items/" + item["id"]
        uploaded = client.patch(path, json={"image_base64": encoded}).json()
        self.assertIsNotNone(uploaded["image_url"])
        self.assertEqual(client.patch(path, json={"name": None}).status_code, 422)
        self.assertEqual(client.patch(path, json={"remove_image": True, "image_base64": encoded}).status_code, 422)
        self.assertIsNone(client.patch(path, json={"remove_image": True}).json()["image_url"])

    def test_font_fallback_without_system_fonts(self):
        # Keep Pillow's built-in fallback real, while making every system lookup fail.
        original = ImageFont.truetype
        def no_system_font(candidate, *args, **kwargs):
            if isinstance(candidate, str):
                raise OSError("unavailable")
            return original(candidate, *args, **kwargs)
        with patch("wardrobe.cards.ImageFont.truetype", side_effect=no_system_font):
            font = font_for(20, "missing-font.ttf")
            self.assertGreater(font.getlength("Wardrobe"), 0)


if __name__ == "__main__":
    unittest.main()
