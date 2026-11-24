"""Acceptance regressions for the restored wardrobe behavior."""
import base64
import io
import json
import sqlite3
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

import test_rules as rules


class RoundTwo(unittest.TestCase):
    setUp = rules.WardrobeRules.setUp
    client = rules.WardrobeRules.client
    add = rules.WardrobeRules.add
    # Reuse setup/helpers, without repeating the inherited test suite.
    def populate(self, client, owner):
        result = {}
        for category in self.config['categories']:
            if owner not in category['owners']:
                continue
            count = 3 if category['id'] == 'toy' else 1
            result[category['id']] = []
            for n in range(count):
                body = dict(name=category['name']+str(n), owner=owner, category=category['id'], added_by='ai',
                            description='一起看一场电影。' if category['text_only'] else '')
                response = client.post('/api/items', json=body)
                self.assertEqual(response.status_code, 201, response.text)
                result[category['id']].append(response.json())
        return result

    def draw(self, client, target='human', **kwargs):
        return client.post('/api/draw', json=dict(chosen_by='human', target=target, **kwargs))

    def test_six_categories_outfit_and_toy_counts(self):
        client = self.client()
        self.populate(client, 'human'); self.populate(client, 'ai')
        for owner, expected in [('human', {'clothes','stockings','accessory','toy'}), ('ai', {'clothes','accessory','toy','medicine','order'})]:
            record = self.draw(client, target=owner, counts={'toy':3}).json()
            self.assertEqual({i['category'] for i in record['items']}, expected)
            self.assertEqual(sum(i['category']=='toy' for i in record['items']), 3)
            self.assertEqual(len({i['id'] for i in record['items']}), len(record['items']))
        self.assertEqual(len(self.draw(client, mode='single', category='toy', counts={'toy':3}).json()['items']), 3)
        self.assertEqual(len(self.draw(client, categories=['toy'], counts={'toy':2}).json()['items']), 2)
        mixed = self.draw(client, categories=['toy','medicine']).json()
        self.assertEqual(len(mixed['items']), 2)
        for body in [dict(counts={'toy':4}),dict(categories=['toy','clothes'],counts={'toy':2}),dict(counts={'medicine':1}),dict(categories=['toy','toy']),dict(category='toy'),dict(count=2)]:
            self.assertEqual(self.draw(client, **body).status_code, 422, body)
        self.assertEqual(client.post('/api/items', json=dict(name='袜子', owner='ai', category='stockings',added_by='human')).status_code, 422)

    def test_pool_and_pick_record_counts_and_limits(self):
        client = self.client(); items=self.populate(client,'human'); foreign=self.add(client,owner='ai')
        pool=[i['id'] for i in items['toy']]+[items['clothes'][0]['id']]
        record=self.draw(client,item_ids=pool,count=2,line='候选里挑两件').json()
        self.assertEqual(len(record['items']),2)
        self.assertTrue({i['id'] for i in record['items']} <= set(pool))
        for item in record['items']:
            detail=client.get('/api/items/'+item['id']).json()
            self.assertEqual(detail['use_count'],1);self.assertEqual(detail['last_used_at'],record['created_at'])
            self.assertEqual(detail['uses'][0]['id'],record['id'])
        for ids,count in [(pool,5),(pool+[foreign['id']],1),([pool[0]]*2,1)]:
            self.assertEqual(self.draw(client,item_ids=ids,count=count).status_code,422)
        self.assertEqual(self.draw(client,item_ids=pool,categories=['toy']).status_code,422)
        self.assertEqual(self.draw(client,item_ids=pool,line='字'*41).status_code,422)
        eight=[self.add(client,name=str(n))['id'] for n in range(8)]
        chosen=client.post('/api/pick',json=dict(chosen_by='human',target='human',item_ids=eight,line='八件')).json()
        self.assertEqual(Image.open(io.BytesIO(client.get(chosen['card_url']).content)).size,(1080,1620))
        self.assertEqual(client.post('/api/pick',json=dict(chosen_by='human',target='human',item_ids=eight+[pool[0]])).status_code,422)

    def test_instruction_requires_body_and_no_photo_on_add_edit(self):
        client=self.client();body=dict(name='一件小事',owner='human',category='order',added_by='ai')
        self.assertEqual(client.post('/api/items',json=body).status_code,422)
        output=io.BytesIO();Image.new('RGB',(20,20)).save(output,'PNG');encoded=base64.b64encode(output.getvalue()).decode()
        self.assertEqual(client.post('/api/items',json=body|{'description':'看电影','image_base64':encoded}).status_code,422)
        item=client.post('/api/items',json=body|{'description':'看电影'*66}).json()
        path='/api/items/'+item['id']
        self.assertEqual(client.patch(path,json={'description':''}).status_code,422)
        self.assertEqual(client.patch(path,json={'image_base64':encoded}).status_code,422)
        record=self.draw(client,categories=['order']).json()
        self.assertIn('看电影'*66,record['text']);self.assertTrue(record['items'][0]['text_only'])
        self.assertEqual(Image.open(io.BytesIO(client.get(record['card_url']).content)).size,(1080,1350))
        photo=self.add(client);path='/api/items/'+photo['id'];client.patch(path,json={'image_base64':encoded})
        self.assertEqual(client.patch(path,json={'category':'order','description':'做一件事'}).status_code,422)
        self.assertEqual(client.patch(path,json={'category':'order','description':'做一件事','remove_image':True}).status_code,200)

    def test_annotation_edit_delete_author_and_confirmation(self):
        client=self.client();item=self.add(client);path='/api/items/'+item['id']
        note=client.post(path+'/notes',json={'author':'human','text':'原批注'}).json();np=path+'/notes/'+note['id']
        self.assertEqual(client.patch(np,json={'author':'ai','text':'别人的'}).status_code,403)
        updated=client.patch(np,json={'author':'human','text':'更正'}).json()
        self.assertEqual(updated['created_at'],note['created_at']);self.assertTrue(updated['updated_at'])
        for author,confirm,status in [('human',False,422),('ai',True,403),('human',True,200)]:
            self.assertEqual(client.request('DELETE',np,json={'author':author,'confirm':confirm}).status_code,status)
        self.assertEqual(client.get(path).json()['notes'],[])
        self.assertEqual(client.patch(path,json={'use_count':4,'last_used_at':'2026-01-01T12:00:00+00:00'}).status_code,200)
        self.assertEqual(client.get(path).json()['use_count'],4)
        self.assertEqual(client.patch(path,json={'use_count':-1}).status_code,422)
        self.assertIsNone(client.patch(path,json={'last_used_at':None}).json()['last_used_at'])

    def test_independent_hooks_human_both_targets_and_unread(self):
        self.config['webhook_url']='https://hooks.example.org/card';self.config['notify_webhook_url']='https://hooks.example.org/notify'
        client=self.client();human=self.add(client);ai=self.add(client,owner='ai')
        ids=[]
        for mode,item in [('draw',human),('pick',ai)]:
            with patch('wardrobe.app.httpx.post',side_effect=[httpx.ReadTimeout('card failed'),httpx.Response(204)]) as send:
                record=client.post('/api/'+mode,json=dict(chosen_by='human',target=item['owner'],**({'item_ids':[item['id']]} if mode=='pick' else {}))).json()
            self.assertEqual(send.call_count,2);self.assertEqual(send.call_args_list[1].kwargs['json']['event'],'wardrobe.notify')
            self.assertEqual(record['webhook']['status'],'unknown');self.assertEqual(record['notification']['status'],'delivered');ids.append(record['id'])
        with patch('wardrobe.app.httpx.post',return_value=httpx.Response(200)) as send:
            record=client.post('/api/draw',json=dict(chosen_by='ai',target='human')).json()
        self.assertEqual(send.call_count,1);self.assertEqual(record['notification']['status'],'not_applicable')
        unread=client.get('/api/unread?limit=1').json();self.assertEqual(unread['remaining'],1)
        self.assertEqual(len(client.get('/api/unread').json()['history']),2)
        client.post('/api/unread/read',json={'record_ids':[ids[0]]})
        self.assertEqual([r['id'] for r in client.get('/api/unread').json()['history']],[ids[1]])
        self.assertEqual(client.post('/api/unread/read',json={'record_ids':[ids[1],record['id']]}).status_code,422)
        self.assertEqual(len(client.get('/api/unread').json()['history']),1) # rollback the whole invalid acknowledgement
        client.post('/api/unread/read',json={'record_ids':[ids[1]]})
        self.assertEqual(client.get('/api/unread').json()['history'],[])
        self.assertEqual(len(client.get('/api/history').json()['history']),3)

    def test_custom_count_limit_and_eight_cell_rejection_is_atomic(self):
        self.config['categories'][0]['max_count']=8
        client=self.client();items=[self.add(client,name=str(n)) for n in range(8)];self.add(client,category='accessory')
        self.assertEqual(self.draw(client,counts={'clothes':8}).status_code,422)
        self.assertEqual(client.get('/api/history').json()['history'],[])
        self.assertEqual(client.get('/api/items/'+items[0]['id']).json()['use_count'],0)
        self.assertEqual(len(self.draw(client,mode='single',category='clothes',counts={'clothes':8}).json()['items']),8)

    def test_existing_database_gains_columns_without_data_loss(self):
        directory=self.directory/'data';directory.mkdir()
        with sqlite3.connect(directory/'wardrobe.sqlite3') as conn:
            conn.executescript('''CREATE TABLE items (id TEXT PRIMARY KEY,name TEXT,owner TEXT,category TEXT,added_by TEXT,description TEXT,image_file TEXT,created_at TEXT,archived INTEGER DEFAULT 0,use_count INTEGER DEFAULT 0);
            CREATE TABLE notes (id TEXT PRIMARY KEY,item_id TEXT,author TEXT,author_name TEXT,text TEXT,created_at TEXT);
            INSERT INTO items VALUES ('old','旧衣服','human','clothes','human','旧备注',NULL,'2026-01-01',0,7);''')
        client=self.client();item=client.get('/api/items/old').json();self.assertEqual(item['use_count'],7);self.assertIsNone(item['last_used_at'])
        self.draw(client);self.assertEqual(client.get('/api/items/old').json()['use_count'],8)
