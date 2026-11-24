"""Real HTTP + stdio MCP smoke test; owns and always sclothes its temporary service."""
import argparse
import asyncio
import base64
import importlib
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
URL = "http://127.0.0.1:18765"


async def check_mcp(env, image_item_id, record_id):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=[str(PROJECT / "wardrobe_mcp.py")], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            available = await session.list_tools()
            assert len(available.tools) == 16
            for name, arguments in [
                ("wardrobe_config", {}), ("wardrobe_list", {}),
                ("wardrobe_link", {}),
                ("wardrobe_view", {"item_id": image_item_id}),
                ("wardrobe_card", {"record_id": record_id}),
            ]:
                result = await session.call_tool(name, arguments)
                assert not result.isError, result
                if name in ("wardrobe_view", "wardrobe_card"):
                    assert any(content.type == "image" for content in result.content), result
    print("PASS MCP stdio initialize, 16 tools, config/list, item image and card image")


async def check_remote_mcp(env, image_item_id, record_id):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    endpoint = URL + "/mcp/" + env['WARDROBE_MCP_KEY']
    async with streamablehttp_client(endpoint) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            assert len((await session.list_tools()).tools) == 16
            for name, arguments in [
                ('wardrobe_config', {}), ('wardrobe_link', {}),
                ('wardrobe_view', {'item_id': image_item_id}),
                ('wardrobe_card', {'record_id': record_id}),
            ]:
                result = await session.call_tool(name, arguments)
                assert not result.isError, result
                if name in ('wardrobe_view', 'wardrobe_card'):
                    assert any(content.type == 'image' for content in result.content)
            result = await session.call_tool('wardrobe_add', {'name': '远程测试围巾', 'owner': 'ai', 'category': 'accessory'})
            assert not result.isError, result
            item = json.loads(result.content[0].text)
            assert not (await session.call_tool('wardrobe_remove', {'item_id': item['id']})).isError
    async with httpx.AsyncClient() as client:
        for key in ('wrong', env['WARDROBE_API_KEY']):
            assert (await client.post(URL + '/mcp/' + key, json={})).status_code == 404
    print('PASS remote MCP SDK handshake, 16 tools, link, images, writes and independent key')


def check_browser(directory, key):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(URL)
        page.locator("#secret").fill("invalid-test-key")
        page.locator("#gate-form button").click()
        page.wait_for_function("document.querySelector('#gate-error').textContent.length > 0")
        page.locator("#secret").fill(key)
        page.locator("#gate-form button").click()
        page.locator("#collection").wait_for(state="visible")
        page.locator('#draw-kinds button').first.wait_for()
        assert page.locator('#draw-kinds button').count() == 6
        assert not page.locator('#category-counts').is_visible()
        assert page.locator('#draw-other').inner_text() == '给小机抽一套'
        page.locator('#draw-kinds [data-kind="toy"]').click()
        assert page.locator('#category-counts select:visible').count() == 1
        assert page.locator('#category-counts select:visible').get_attribute('data-category') == 'toy'
        page.locator('#draw-kinds [data-kind="toy"]').click()
        assert not page.locator('#category-counts').is_visible()
        page.locator("#add").click()
        page.locator("#name").fill("浏览器测试围巾")
        page.locator("#kind").select_option("accessory")
        image = directory / "browser-photo.png"
        Image.new("RGB", (80, 100), "#d8b991").save(image)
        page.locator("#image").set_input_files(str(image))
        page.locator("#note").fill("浏览器上传验证")
        page.locator("#save").click()
        page.locator("#editor-dialog").wait_for(state="hidden")
        page.get_by_role("button", name="查看浏览器测试围巾", exact=True).click()
        page.locator("#note-text").fill("网页写的批注")
        page.locator("#note-form button").click()
        page.get_by_text("网页写的批注", exact=True).wait_for()
        page.get_by_role('button', name='修改批注', exact=True).click()
        page.locator('#note-edit-text').fill('更正后的批注')
        page.locator('#note-edit-form button').click()
        page.get_by_text('更正后的批注', exact=True).wait_for()
        page.once('dialog', lambda dialog: dialog.dismiss())
        page.get_by_role('button', name='删除批注', exact=True).click()
        assert page.get_by_text('更正后的批注', exact=True).is_visible()
        page.once('dialog', lambda dialog: dialog.accept())
        page.get_by_role('button', name='删除批注', exact=True).click()
        page.get_by_text('更正后的批注', exact=True).wait_for(state='hidden')
        page.locator("#edit").click()
        page.locator("#name").fill("浏览器测试围巾（已编辑）")
        page.locator("#save").click()
        page.locator("#editor-dialog").wait_for(state="hidden")
        page.locator('#back-list').click()
        page.get_by_role("checkbox", name="挑选浏览器测试围巾（已编辑）", exact=True).check()
        page.get_by_role("checkbox", name="挑选白袜子", exact=True).check()
        page.locator('#pick-line').fill('这句话只属于这次卡片')
        page.locator('#pool-count').select_option('1')
        page.locator('#pool-submit').click()
        page.get_by_role('button', name='查看这次卡片', exact=True).wait_for()
        page.get_by_role('button', name='查看这次卡片', exact=True).click()
        page.wait_for_function("document.querySelector('#zoom-image').complete && document.querySelector('#zoom-image').naturalWidth > 0")
        page.locator('#zoom-dialog [data-close]').click()
        page.get_by_role("checkbox", name="挑选浏览器测试围巾（已编辑）", exact=True).check()
        page.get_by_role("checkbox", name="挑选白袜子", exact=True).check()
        page.locator('#pick-line').fill('手挑附言')
        page.locator('#pick-submit').click()
        page.get_by_role('button', name='查看这次卡片', exact=True).wait_for()
        page.locator('[data-draw="set"]').click()
        page.locator('#outfit-dialog').wait_for(state='visible')
        assert page.locator('#outfit-counts select').count() == 1
        assert page.locator('#outfit-counts select').get_attribute('data-category') == 'toy'
        page.locator('#outfit-counts select').select_option('3')
        page.locator('#outfit-form button[type="submit"]').click()
        page.get_by_role('button', name='查看这次卡片', exact=True).wait_for()
        page.locator('#draw-kinds [data-kind="clothes"]').click()
        page.locator('#draw-kinds [data-kind="accessory"]').click()
        page.locator('#draw-selected').click()
        page.get_by_role('button', name='查看这次卡片', exact=True).wait_for()
        page.locator('#history-open').click()
        page.locator('.history-row').first.wait_for()
        page.locator('#history-dialog [data-close]').click()
        page.wait_for_function("[...document.querySelectorAll('#grid img')].every(img => img.complete && img.naturalWidth > 0)")
        page.screenshot(path=str(directory / "desktop.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(directory / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.locator('#owners [data-owner="ai"]').click()
        page.wait_for_function("document.querySelectorAll('#draw-kinds button').length===5")
        assert page.locator('#draw-kinds [data-kind="stockings"]').count() == 0
        page.locator('#add').click()
        page.locator('#kind').select_option('order')
        assert not page.locator('#photo-field').is_visible()
        page.locator('#name').fill('浏览器指令')
        page.locator('#note').fill('一起看一场电影。')
        page.locator('#save').click()
        page.locator('#editor-dialog').wait_for(state='hidden')
        page.get_by_role('button',name='查看浏览器指令',exact=True).wait_for()
        page.reload()
        page.locator("#collection").wait_for(state="visible")
        page.locator('#lock').click()
        assert page.evaluate("localStorage.getItem('wardrobe_secret')") is None
        assert not errors, errors
        browser.close()
    print("PASS browser login, upload/edit, annotation edit/delete confirmation, pool/pick/mixed/outfit, cards, history, instruction, roles, persisted login/logout, desktop/mobile overflow and JS errors")


def run(browser=False, artifacts=None):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 18765))
    with tempfile.TemporaryDirectory(prefix="wardrobe-smoke-") as temp:
        directory = Path(temp)
        config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
        config["public_base_url"] = URL
        config_file = directory / "config.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")
        key = secrets.token_urlsafe(32)
        env = {**os.environ, "WARDROBE_API_KEY": key, "WARDROBE_CONFIG": str(config_file),
               "WARDROBE_DATA_DIR": str(directory / "data"), "WARDROBE_URL": URL,
               "WARDROBE_MCP_KEY": secrets.token_urlsafe(32), "PUBLIC_URL": URL,
               "PYTHONDONTWRITEBYTECODE": "1"}
        with (directory / "server.log").open("w+") as log:
            process = subprocess.Popen([sys.executable, "-m", "wardrobe", "--port", "18765"], cwd=PROJECT, env=env, stdout=log, stderr=log)
            try:
                with httpx.Client(base_url=URL, headers={"Authorization": "Bearer " + key}, timeout=30) as client:
                    for _ in range(100):
                        if process.poll() is not None:
                            log.seek(0)
                            raise RuntimeError(log.read())
                        try:
                            if client.get("/health").status_code == 200:
                                break
                        except httpx.ConnectError:
                            pass
                        time.sleep(.1)
                    else:
                        raise RuntimeError("服务未及时启动")
                    def call(method, path, body=None, expected=200):
                        response = client.request(method, path, json=body)
                        assert response.status_code == expected, (method, path, response.status_code, response.text)
                        return response.json()

                    assert httpx.get(URL + "/api/items").status_code == 401
                    assert httpx.get(URL + "/api/config?token=" + key).status_code == 401
                    assert client.get("/").status_code == 200
                    public = call("GET", "/api/config")
                    assert "webhook_url" not in public and "font_path" not in public
                    print("PASS auth, no query-token access, page and safe config")

                    output = io.BytesIO(); Image.new("RGB", (90, 120), "#b4c9b0").save(output, "PNG")
                    encoded = base64.b64encode(output.getvalue()).decode()
                    items = []
                    for index, source in enumerate(json.loads((PROJECT / "examples" / "items.json").read_text(encoding="utf-8"))):
                        body = {**source, "added_by": "human"}
                        if index == 0:
                            body["image_base64"] = encoded
                        items.append(call("POST", "/api/items", body, 201))
                    listed = call("GET", "/api/items?owner=human")["items"]
                    assert len(listed) == 4
                    image_response = client.get(items[0]["image_url"])
                    assert Image.open(io.BytesIO(image_response.content)).format == "JPEG"
                    assert httpx.get(items[0]["image_url"]).status_code == 401
                    print("PASS add five neutral items, list by owner, upload and authenticated image")

                    draw = call("POST", "/api/draw", {"chosen_by": "human", "target": "human"}, 201)
                    assert len(draw["items"]) == 3 and draw["webhook"]["status"] == "disabled"
                    pick = call("POST", "/api/pick", {"chosen_by": "ai", "target": "human", "item_ids": [items[0]["id"], items[2]["id"]], "line": "测试搭配"}, 201)
                    assert len(pick["items"]) == 2 and pick["chosen_by"] == "ai" and pick["target"] == "human"
                    card = client.get(pick["card_url"])
                    assert Image.open(io.BytesIO(card.content)).format == "PNG"
                    note = call("POST", f'/api/items/{items[0]["id"]}/notes', {"author": "ai", "text": "适合日常穿着"}, 201)
                    assert note["author"] == "ai"
                    details = call("GET", f'/api/items/{items[0]["id"]}')
                    assert details["notes"][0]["text"] == "适合日常穿着" and details["use_count"] >= 1 and details["last_used_at"]
                    history = call("GET", "/api/history?target=human")["history"]
                    assert len(history) == 2 and history[0]["id"] == pick["id"]
                    assert len(call("GET", "/api/history?limit=1&offset=1")["history"]) == 1
                    print("PASS draw outfit, pick two, actor/target, card, note, history and pagination")

                    call("PATCH", f'/api/items/{items[0]["id"]}', {"name": "白衬衫（修改后）"})
                    assert call("GET", "/api/history")["history"][0]["items"][0]["name"] == "白衬衫"
                    call("POST", "/api/pick", {"chosen_by": "ai", "target": "human", "item_ids": [items[0]["id"]] * 2}, 422)
                    call("POST", "/api/pick", {"chosen_by": "ai", "target": "human", "item_ids": [items[4]["id"]]}, 422)
                    call("POST", "/api/draw", {"chosen_by": "ai", "target": "ai", "mode": "single", "category": "toy"}, 409)
                    call("POST", "/api/items", {"name": "bad", "owner": "human", "category": "missing", "added_by": "ai"}, 422)
                    call("PATCH", f'/api/items/{items[0]["id"]}', {"image_base64": "not-an-image"}, 422)
                    call("POST", "/api/items", {"name": "   ", "owner": "human", "category": "clothes", "added_by": "ai"}, 422)
                    print("PASS edits preserve history; duplicate, wrong-owner, empty-pool and invalid-input rejection")

                    module = importlib.import_module("wardrobe_mcp")
                    previous = dict(os.environ)
                    try:
                        os.environ.update(env)
                        assert len(module.wardrobe_list()["items"]) == 5
                        added = module.wardrobe_add("MCP 测试帽子", "ai", "accessory")
                        module.wardrobe_edit(added["id"], description="MCP 编辑")
                        module.wardrobe_note(added["id"], "MCP 备注")
                        single = module.wardrobe_draw("ai", "single", "accessory")
                        assert single["chosen_by"] == "ai"
                        module.wardrobe_pick("ai", [added["id"]])
                        assert len(module.wardrobe_history("ai")["history"]) == 2
                        module.wardrobe_remove(added["id"])
                    finally:
                        os.environ.clear(); os.environ.update(previous)
                    print("PASS MCP import and all write tool adapters over real HTTP")
                    unread = call("GET", "/api/unread")["history"]
                    assert [row["id"] for row in unread] == [draw["id"]]
                    call("POST", "/api/unread/read", {"record_ids": [draw["id"]]})
                    assert call("GET", "/api/unread")["history"] == []
                    asyncio.run(check_mcp(env, items[0]["id"], pick["id"]))
                    asyncio.run(check_remote_mcp(env, items[0]["id"], pick["id"]))

                    if browser:
                        output_dir = Path(artifacts) if artifacts else directory
                        output_dir.mkdir(parents=True, exist_ok=True)
                        check_browser(output_dir, key)
                    call("DELETE", f'/api/items/{items[0]["id"]}')
                    call("GET", f'/api/items/{items[0]["id"]}', expected=404)
                    assert client.get(pick["card_url"]).status_code == 200
                    print("PASS remove preserves historical card")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
                print("STOP temporary HTTP service")
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", 18765)) != 0
        print("PASS port 18765 released; temporary data cleaned on exit")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--artifacts", help="可选：保留浏览器测试的合成截图")
    args = parser.parse_args()
    run(args.browser, args.artifacts)
