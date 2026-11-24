"""Exercise the actual ASGI middleware and Streamable HTTP JSON-RPC transport."""
import asyncio
import io
import json
import os
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from PIL import Image

import wardrobe_mcp
from wardrobe.app import create_app
from wardrobe.config import BASE, load_settings


class RemoteMCP(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.key = secrets.token_urlsafe(32)
        self.web_key = secrets.token_urlsafe(32)
        self.env = patch.dict(os.environ, {
            'WARDROBE_API_KEY': self.web_key, 'WARDROBE_MCP_KEY': self.key,
            'WARDROBE_DATA_DIR': self.temp.name, 'WARDROBE_CONFIG': str(BASE / 'config.json'),
            'PUBLIC_URL': 'https://wardrobe.example.org', 'WARDROBE_URL': 'http://unused.invalid',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        # Some restricted hosts suppress cross-thread event-loop wakeup socket writes.
        # This timer keeps their selector awake; app/ASGI/tool execution is unmodified.
        if os.environ.get('WARDROBE_TEST_DIRECT') == '1':
            async def tick():
                while True:
                    await asyncio.sleep(.01)
            task = asyncio.create_task(tick())
            self.addCleanup(task.cancel)
        self.app = create_app()
        self.life = self.app.router.lifespan_context(self.app)
        await self.life.__aenter__()
        self.addAsyncCleanup(self.life.__aexit__, None, None, None)
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                     base_url='https://wardrobe.example.org')
        self.addAsyncCleanup(self.http.aclose)
        self.endpoint = '/mcp/' + self.key
        self.headers = {'Accept': 'application/json, text/event-stream'}
        self.auth = {'Authorization': 'Bearer ' + self.web_key}

    async def rpc(self, method, params, endpoint=None):
        response = await self.http.post(endpoint or self.endpoint, headers=self.headers,
                                       json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        result = response.json()
        self.assertNotIn('error', result, result)
        return result['result']

    async def call(self, tool_name, **arguments):
        result = await self.rpc('tools/call', {'name': tool_name, 'arguments': arguments})
        self.assertFalse(result.get('isError'), result)
        return result

    @staticmethod
    def data(result):
        return json.loads(result['content'][0]['text'])

    async def test_handshake_tool_parity_and_path_auth(self):
        init = await self.rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                            'clientInfo': {'name': 'test', 'version': '1'}})
        self.assertEqual(init['serverInfo']['name'], 'our-wardrobe')
        response = await self.http.post(self.endpoint, headers=self.headers,
                                       json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        self.assertEqual(response.status_code, 202)
        remote = (await self.rpc('tools/list', {}))['tools']
        local = await wardrobe_mcp.mcp.list_tools()
        self.assertEqual({t['name']: t['inputSchema'] for t in remote}, {t.name: t.inputSchema for t in local})
        self.assertEqual(len(remote), 16)
        results = await asyncio.gather(self.call('wardrobe_config'), self.call('wardrobe_link'))
        self.assertEqual(self.data(results[0])['clients']['mcp'], 'ai')
        link = await self.rpc('tools/call', {'name': 'wardrobe_link', 'arguments': {}}, self.endpoint + '/')
        self.assertEqual(self.data(link), {'label': '打开衣柜', 'url': 'https://wardrobe.example.org/'})
        for path in ('/mcp/', '/mcp/wrong', '/mcp/' + self.web_key, self.endpoint + '/extra'):
            response = await self.http.post(path, headers={**self.headers, **self.auth}, json={})
            self.assertEqual(response.status_code, 404)
        response = await self.http.get('/api/link', headers={'Authorization': 'Bearer ' + self.key})
        self.assertEqual(response.status_code, 401)
        for headers in ({'Host': 'unexpected.example'}, {'Origin': 'https://unexpected.example'}):
            response = await self.http.post(self.endpoint, headers={**self.headers, **headers}, json={})
            self.assertIn(response.status_code, (403, 421))
        self.assertEqual((await self.http.get(self.endpoint, headers=self.headers)).status_code, 405)

    async def test_remote_writes_images_hooks_unread_and_link(self):
        imports = self.directory / 'mcp-imports'
        imports.mkdir()
        Image.new('RGB', (24, 30), 'white').save(imports / 'shirt.png')
        first = self.data(await self.call('wardrobe_add', name='白衬衫', owner='human', category='clothes', image_path='shirt.png'))
        await self.call('wardrobe_edit', item_id=first['id'], description='修改后的短备注')
        detail = await self.call('wardrobe_view', item_id=first['id'])
        self.assertTrue(any(c['type'] == 'image' for c in detail['content']))
        note = self.data(await self.call('wardrobe_note', item_id=first['id'], text='批注'))
        await self.call('wardrobe_note_edit', item_id=first['id'], note_id=note['id'], text='更正')
        await self.call('wardrobe_note_delete', item_id=first['id'], note_id=note['id'], confirm=True)
        draw = self.data(await self.call('wardrobe_draw', target='human', chosen_by='human'))
        pick = self.data(await self.call('wardrobe_pick', target='human', item_ids=[first['id']]))
        for record in (draw, pick):
            self.assertEqual(record['wardrobe_url'], 'https://wardrobe.example.org/')
            self.assertIn('打开衣柜：https://wardrobe.example.org/', record['text'])
            self.assertNotIn(self.key, json.dumps(record))
            self.assertNotIn(self.web_key, json.dumps(record))
        card = await self.call('wardrobe_card', record_id=pick['id'])
        self.assertTrue(any(c['type'] == 'image' for c in card['content']))
        unread = self.data(await self.call('wardrobe_unread'))
        self.assertEqual([r['id'] for r in unread['history']], [draw['id']])
        await self.call('wardrobe_mark_read', record_ids=[draw['id']])
        self.assertEqual(self.data(await self.call('wardrobe_unread'))['history'], [])
        self.assertEqual(len(self.data(await self.call('wardrobe_history'))['history']), 2)
        self.assertEqual(len(self.data(await self.call('wardrobe_list'))['items']), 1)
        await self.call('wardrobe_remove', item_id=first['id'])
        # A remote user cannot read arbitrary server files, even with a valid MCP key.
        denied = await self.rpc('tools/call', {'name': 'wardrobe_add', 'arguments': {
            'name': '拒绝', 'owner': 'human', 'category': 'clothes', 'image_path': '../config.json'}})
        self.assertTrue(denied['isError'])

    async def test_static_manifest_icons_and_disabled_remote(self):
        response = await self.http.get('/static/manifest.webmanifest')
        manifest = response.json()
        self.assertEqual(manifest['start_url'], '/')
        self.assertEqual(manifest['display'], 'standalone')
        for icon in manifest['icons']:
            response = await self.http.get(icon['src'])
            image = Image.open(io.BytesIO(response.content))
            self.assertEqual('x'.join(map(str, image.size)), icon['sizes'])
        with patch.dict(os.environ, {'WARDROBE_MCP_KEY': ''}):
            app = create_app()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
                self.assertEqual((await client.post(self.endpoint, json={})).status_code, 404)
        for value in ('short', self.web_key, 'bad/character' * 4):
            with patch.dict(os.environ, {'WARDROBE_MCP_KEY': value}), self.assertRaises(RuntimeError):
                create_app()


class PublicLinks(unittest.TestCase):
    def test_public_url_validation_and_webhook_links(self):
        from direct_client import DirectClient
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            'WARDROBE_API_KEY': 'test', 'WARDROBE_MCP_KEY': '', 'PUBLIC_URL': 'https://wardrobe.example.org',
            'WARDROBE_DATA_DIR': temp, 'WARDROBE_CONFIG': str(Path(temp) / 'config.json'),
        }):
            config = json.loads((BASE / 'config.json').read_text())
            config.update(webhook_url='https://hooks.example.org/card', notify_webhook_url='https://hooks.example.org/notice')
            Path(temp, 'config.json').write_text(json.dumps(config))
            client = DirectClient(create_app(), {'Authorization': 'Bearer test'})
            client.post('/api/items', json={'name': '测试', 'category': 'clothes', 'owner': 'human', 'added_by': 'human'})
            with patch('wardrobe.app.httpx.post', return_value=httpx.Response(200)) as send:
                result = client.post('/api/draw', json={'target': 'human', 'chosen_by': 'human'}).json()
            self.assertEqual(send.call_count, 2)
            for sent in send.call_args_list:
                self.assertEqual(sent.kwargs['json']['wardrobe_url'], 'https://wardrobe.example.org/')
            self.assertIn('打开衣柜', result['text'])
            for value in ('', 'ftp://example.org', 'https://example.org/sub', 'https://example.org/?secret=bad'):
                with patch.dict(os.environ, {'PUBLIC_URL': value}), self.assertRaises(ValueError):
                    load_settings()


if __name__ == '__main__':
    unittest.main()
