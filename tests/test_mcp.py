"""Validate every MCP adapter against the service routes without network I/O."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import wardrobe_mcp
from wardrobe.app import create_app
from wardrobe.config import BASE
from direct_client import DirectClient


class MCPAdapters(unittest.TestCase):
    def test_import_registration_and_all_adapters(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            config_path = directory / "config.json"
            config_path.write_text((BASE / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
            environment = {"WARDROBE_CONFIG": str(config_path), "WARDROBE_DATA_DIR": str(directory / "data"),
                           "WARDROBE_API_KEY": "temporary-test-key", "WARDROBE_URL": "http://testserver"}
            with patch.dict(os.environ, environment):
                client = DirectClient(create_app(), {"Authorization": "Bearer temporary-test-key"})
                def send(method, url, **kwargs):
                    self.assertEqual(kwargs["headers"]["Authorization"], "Bearer temporary-test-key")
                    return client.request(method, url, kwargs.get("json"))
                with patch("wardrobe_mcp.httpx.request", side_effect=send):
                    tools = wardrobe_mcp.mcp._tool_manager.list_tools()
                    self.assertEqual(len(tools), 16)
                    self.assertEqual(wardrobe_mcp.wardrobe_config()["clients"]["mcp"], "ai")
                    self.assertEqual(wardrobe_mcp.wardrobe_link()["label"], "打开衣柜")
                    image = directory / "test.png"
                    Image.new("RGB", (30, 50), "white").save(image)
                    first = wardrobe_mcp.wardrobe_add("白衬衫", "human", "clothes", image_path=str(image))
                    second = wardrobe_mcp.wardrobe_add("白袜子", "human", "stockings")
                    self.assertEqual(len(wardrobe_mcp.wardrobe_list("human")["items"]), 2)
                    wardrobe_mcp.wardrobe_edit(first["id"], description="修改后的描述")
                    wardrobe_mcp.wardrobe_note(first["id"], "写一条备注")
                    detail = wardrobe_mcp.wardrobe_view(first["id"])
                    self.assertEqual(len(detail), 2)
                    self.assertEqual(json.loads(detail[0])["notes"][0]["author"], "ai")
                    tool = wardrobe_mcp.mcp._tool_manager.get_tool("wardrobe_view")
                    content = tool.fn_metadata.convert_result(detail)
                    self.assertTrue(any(part.type == "image" for part in content))
                    note = wardrobe_mcp.wardrobe_note(first["id"], "要改的批注")
                    changed = wardrobe_mcp.wardrobe_note_edit(first["id"], note["id"], "更正")
                    self.assertEqual(changed["text"], "更正")
                    with self.assertRaises(ValueError):
                        wardrobe_mcp.wardrobe_note_delete(first["id"], note["id"])
                    wardrobe_mcp.wardrobe_note_delete(first["id"], note["id"], confirm=True)
                    wardrobe_mcp.wardrobe_edit(first["id"], use_count=2, last_used_at="2026-01-01T00:00:00Z")
                    wardrobe_mcp.wardrobe_edit(first["id"], clear_last_used_at=True)
                    pool = wardrobe_mcp.wardrobe_draw("human", item_ids=[first["id"],second["id"]], count=1, chosen_by="human")
                    unread = wardrobe_mcp.wardrobe_unread()
                    self.assertEqual(unread["history"][0]["id"], pool["id"])
                    wardrobe_mcp.wardrobe_mark_read([pool["id"]])
                    self.assertEqual(wardrobe_mcp.wardrobe_unread()["history"], [])
                    draw = wardrobe_mcp.wardrobe_draw("human")
                    self.assertEqual(draw["chosen_by"], "ai")
                    pick = wardrobe_mcp.wardrobe_pick("human", [first["id"], second["id"]])
                    self.assertEqual(len(wardrobe_mcp.wardrobe_card(pick["id"])), 2)
                    self.assertEqual(len(wardrobe_mcp.wardrobe_history("human")["history"]), 3)
                    wardrobe_mcp.wardrobe_remove(first["id"])
                    self.assertEqual(len(wardrobe_mcp.wardrobe_list()["items"]), 1)


if __name__ == "__main__":
    unittest.main()
