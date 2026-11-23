"""Reproduce one-click creation with the existing fictional matcha fixture."""
import io
import json
import os
from pathlib import Path
import sys
import time
import uuid
from unittest.mock import patch
from zipfile import ZipFile
from PIL import Image, ImageOps, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / '.trupic/auto-create-proof'
OUT.mkdir(parents=True, exist_ok=True)
os.environ['TRUPIC_DATA'] = str(OUT / ('workspace-' + uuid.uuid4().hex[:8]))
os.environ['TRUPIC_CUTOUT'] = '/missing-no-network'
from server import app as studio

client = studio.app.test_client()
client.get('/api/state')
source = ROOT / '.trupic/skill-proof/final/sources/front.png'
with source.open('rb') as f:
    response = client.post('/api/assets', data={'image': (f, '春山抹茶粉演示.png')})
assert response.status_code == 200, response.json
asset = response.json['id']
brief = '春山抹茶粉新品上市，净含量100g，48元/罐，可搭配牛奶冲调。帮我做一套上新图片，再配一条9秒短视频，主标题写成「给牛奶加一点春山」。'
q = client.post('/api/creations/plan', json=dict(asset=asset, brief=brief)).json
assert q.get('ready'), q
selection = client.post('/api/copy-options', json={'quote':q['quote']}).json
assert len(selection.get('options', [])) >= 2, selection
payload = dict(quote=q['quote'], copyChoice=selection['options'][1]['token'], confirmedCost=q['cost'], requestKey=uuid.uuid4().hex)
with patch.object(studio.model, 'chat_request', side_effect=AssertionError('选稿后应直接制作')):
    result = client.post('/api/creations', json=payload).json
    assert 'id' in result, result
    assert client.post('/api/creations', json=payload).json['id'] == result['id']
    for _ in range(1200):
        result = client.get('/api/creations/' + result['id']).json
        if not result['active']:
            break
        time.sleep(.1)
    assert result['complete'], result
bundle = client.get(result['download'])
assert bundle.status_code == 200
(OUT / '创作成品.zip').write_bytes(bundle.data)
with ZipFile(io.BytesIO(bundle.data)) as archive:
    archive.extractall(OUT / 'deliveries')
shared = studio.quotes.loads(q['quote'])
(OUT / 'report.json').write_text(json.dumps(dict(brief=brief, cost=q['cost'], result=result, shared=shared['shared']), ensure_ascii=False, indent=2))
thumbs = []
for n, item in enumerate(result['items']):
    if item.get('preview'):
        image = Image.open(io.BytesIO(client.get(item['preview']).data)).convert('RGB')
        tile = Image.new('RGB', (360, 430), '#e8e8e4')
        fitted = ImageOps.contain(image, (340, 390))
        tile.paste(fitted, ((360-fitted.width)//2, 10))
        ImageDraw.Draw(tile).text((12, 408), item['role'], fill='black')
        thumbs.append(tile)
sheet = Image.new('RGB', (360*len(thumbs), 430), 'white')
for n, tile in enumerate(thumbs):
    sheet.paste(tile, (n*360, 0))
sheet.save(OUT / 'contact-sheet.jpg')
print(json.dumps(dict(output=str(OUT), deliveries=[i['label'] for i in result['items']], credits=client.get('/api/state').json['credits']), ensure_ascii=False))
