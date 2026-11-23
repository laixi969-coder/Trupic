"""Live provider model discovery and actual, asynchronous capability probes."""
import base64
import io
import json
import os
import threading
import secrets
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, urlunsplit, urlencode
from PIL import Image
from flask import abort, jsonify, send_file
from . import model, providers
from .store import DATA, db, dump, ident, now
from .video_api import request_json, prepare_background

PROBES = ThreadPoolExecutor(max_workers=2,thread_name_prefix='model-probe')
PROBE_LOCK = threading.Lock()


def write_status(folder, result):
    temporary = folder / 'status.tmp'
    temporary.write_text(dump(result))
    temporary.replace(folder / 'status.json')


def probe_signature(cfg):
    return providers.catalog_signature(cfg) + ':' + cfg['model'] + ':' + cfg.get('protocol','chat')



def models_endpoint(cfg):
    if cfg.get('modelsUrl'):
        url = cfg['modelsUrl']
    else:
        parts = urlsplit(cfg['url'])
        if parts.hostname and ('maas.aliyuncs.com' in parts.hostname or 'dashscope' in parts.hostname):
            path = '/api/v1/models'
        else:
            path = parts.path
            for suffix in ('/chat/completions','/images/generations','/images/edits','/contents/generations/tasks'):
                if path.endswith(suffix):
                    path = path[:-len(suffix)] + '/models'
                    break
            else:
                raise ValueError('请填写该平台的模型列表完整地址。')
        url = urlunsplit((parts.scheme,parts.netloc,path,'',''))
    providers.safe_url(url)
    source, target = urlsplit(cfg['url']), urlsplit(url)
    if (source.scheme,source.netloc)!=(target.scheme,target.netloc):
        raise ValueError('模型列表地址须与当前连接同源。')
    return url


def model_row(row):
    name = row.get('id') or row.get('model')
    if not isinstance(name,str) or not name or len(name)>180:
        return None
    modality = row.get('modalities') or row.get('inference_metadata') or row
    inputs = [str(v).lower() for v in modality.get('input_modalities',modality.get('request_modality',[]))]
    outputs = [str(v).lower() for v in modality.get('output_modalities',modality.get('response_modality',[]))]
    caps = row.get('capabilities') or row.get('task_type') or []
    domain = row.get('domain') or ''
    kinds = []
    if 'text' in outputs or 'TG' in caps or 'TextGeneration' in caps or domain in ('LLM','VLM'):
        kinds.append('text')
    if ('image' in inputs and 'text' in outputs) or 'VU' in caps or 'VisualQuestionAnswering' in caps or domain == 'VLM':
        kinds.append('vision')
    if 'image' in outputs or 'IG' in caps or domain == 'ImageGeneration':
        kinds.append('image')
    if ('image' in inputs and 'image' in outputs) or 'ImageEditing' in caps:
        kinds.append('edit')
    if 'video' in outputs or 'VG' in caps or domain == 'VideoGeneration':
        kinds.append('video')
    return dict(id=name,kinds=kinds,known=bool(inputs or outputs or caps or domain),created=row.get('published_time') or row.get('created'))


def sync_models(kind,cfg):
    endpoint = models_endpoint(cfg)
    page, rows, seen, cursor = 1, [], set(), None
    while page <= 50:
        params = dict(page_no=page,page_size=100) if '/api/v1/models' in endpoint else dict(after=cursor) if cursor else {}
        url = endpoint + ('?'+urlencode(params) if params else '')
        result = request_json(cfg,url)
        if result.get('success') is False or result.get('error'):
            raise ValueError('平台未返回模型目录，请核对模型列表接口和权限。')
        output = result.get('output') or {}
        values = output.get('models') if isinstance(output,dict) and 'models' in output else result.get('data')
        if not isinstance(values,list):
            raise ValueError('模型列表响应格式不受支持，请填写 Models API 地址。')
        before = len(seen)
        for value in values:
            row = model_row(value) if isinstance(value,dict) else None
            if row and row['id'] not in seen:
                rows.append(row); seen.add(row['id'])
        total = output.get('total',len(rows)) if isinstance(output,dict) else len(rows)
        if result.get('has_more') is True:
            cursor = result.get('last_id')
            if not isinstance(cursor,str) or not cursor:
                raise ValueError('平台未提供下一页游标，未覆盖上次同步结果。')
        elif not isinstance(total,int) or len(rows)>=total:
            break
        if len(seen)==before:
            raise ValueError('模型列表分页未推进，未覆盖上次同步结果。')
        page += 1
    else:
        raise ValueError('模型列表超过分页上限，未覆盖上次同步结果。')
    updated = now()
    with db(True) as c:
        c.execute('INSERT INTO model_catalog VALUES(?,?,?,?,?) ON CONFLICT(platform,kind) DO UPDATE SET signature=excluded.signature,data=excluded.data,updated=excluded.updated',(cfg['provider'],kind,providers.catalog_signature(cfg),dump(rows),updated))
    return dict(models=rows,updated=updated,source=endpoint)


def probe_image(cfg, folder):
    model.reserve_provider_call('image')
    result = request_json(cfg,cfg['url'],dict(model=cfg['model'],prompt='A green ceramic cup on a neutral background. No text.',size='1024x1024',n=1,response_format='b64_json'),limit=32_000_000)
    encoded = result['data'][0]['b64_json']
    raw = base64.b64decode(encoded,validate=True)
    if len(raw)>24_000_000:
        raise ValueError('图片响应过大。')
    with Image.open(io.BytesIO(raw)) as image:
        if image.width*image.height>24_000_000 or min(image.size)<320:
            raise ValueError('返回图片尺寸不适用。')
        image.convert('RGB').save(folder/'image.png')
    return dict(message='已收到并解码实际生成图片。',preview='image.png')


def execute_probe(folder,kind,cfg):
    started = time.monotonic()
    result = dict(id=folder.name,state='running',kind=kind,model=cfg['model'],signature=probe_signature(cfg),worker=os.getpid())
    write_status(folder,result)
    try:
        if kind == 'text':
            reply = model.chat_request(cfg,cfg['model'],[dict(role='user',content='Return only JSON: {"ok":true}')],100,'text')
            if reply.get('ok') is not True:
                raise ValueError('模型响应成功，但未返回约定的 JSON。')
            detail = dict(message='已收到有效文案模型响应。')
        elif kind == 'vision':
            from .visual_review import image_message
            color = secrets.choice(['red','green','blue','yellow'])
            reply = model.chat_request(cfg,cfg['model'],[dict(role='user',content=image_message('Identify the solid color. Return JSON {"color":"red|green|blue|yellow"}.',Image.new('RGB',(224,224),color)))],150,'vision')
            if reply.get('color')!=color:
                raise ValueError('模型已响应，但未正确识别测试图片。')
            detail = dict(message='已正确识别实际测试图片。')
        elif kind == 'edit':
            from .region_edit import cloud_patch
            image = cloud_patch(cfg, Image.new("RGB",(512,512),"red"), "将红色背景改为蓝色。")
            r, g, b = image.resize((1,1)).getpixel((0,0))
            if b <= r or b <= g:
                raise ValueError("模型返回了图片，但未按要求修改背景。")
            image.save(folder/"image.png")
            detail = dict(message="已验证图片输入与局部改色。",preview="image.png")
        elif kind == 'image':
            detail = probe_image(cfg,folder)
        else:
            plan = dict(output=dict(width=720,height=1280),coordination=dict(product='茶饮',concept='柔和的绿色摄影环境'))
            prepare_background(folder,plan,dict(storyboard=[dict(line='柔和光线',camera='缓慢推进')]),cfg=cfg)
            detail = dict(message='视频任务成功，已下载并解码 216 帧。',preview='cloud-background.mp4')
        result.update(state='complete',**detail)
    except urllib.error.HTTPError as exc:
        reasons = {401:'密钥无效',403:'没有调用权限',404:'接口地址或模型不存在',429:'请求限流或额度不足'}
        result.update(state='failed',error=f'HTTP {exc.code}：'+reasons.get(exc.code,'平台请求失败'))
    except Exception as exc:
        message = str(exc) if isinstance(exc,ValueError) else '连接、响应解析或文件解码失败，请核对接口与模型。'
        result.update(state='failed',error=message[:240])
    result['ms'] = round((time.monotonic()-started)*1000)
    result['completed'] = now()
    write_status(folder,result)
    if kind=='image':
        with db(True) as c:
            c.execute('INSERT INTO model_call(day,kind,platform,model,ok,ms) VALUES(?,?,?,?,?,?)',(now()[:10],kind,cfg['provider'],cfg['model'],result['state']=='complete',result['ms']))


def register(app,services):
    @app.post('/api/admin/sync-models')
    def sync_provider_models():
        services['require_admin']()
        kind,cfg = providers.candidate(services['body'](),require_model=False)
        try:
            return jsonify(sync_models(kind,cfg))
        except urllib.error.HTTPError as exc:
            raise ValueError(f'模型同步失败（HTTP {exc.code}），请检查列表地址、密钥和权限；原有目录保持不变。') from exc
        except OSError as exc:
            raise ValueError('模型同步连接失败，原有目录保持不变。') from exc

    @app.post('/api/admin/probes')
    def create_probe():
        services['require_admin']()
        kind,cfg = providers.candidate(services['body']())
        folder = DATA/'connection-probes'/ident()
        folder.mkdir(parents=True)
        write_status(folder,dict(id=folder.name,state='queued',kind=kind,model=cfg['model'],signature=probe_signature(cfg),worker=os.getpid()))
        PROBES.submit(execute_probe,folder,kind,cfg)
        return jsonify(id=folder.name,state='queued')

    def probe_folder(id):
        if len(id)!=32 or any(ch not in '0123456789abcdef' for ch in id): abort(404)
        folder = DATA/'connection-probes'/id
        if not (folder/'status.json').is_file(): abort(404)
        return folder

    @app.get('/api/admin/probes/<id>')
    def probe_status(id):
        services['require_admin']()
        result = json.loads((probe_folder(id)/'status.json').read_text())
        if result['state'] in ('queued','running'):
            try:
                os.kill(result.get('worker',0),0)
            except ProcessLookupError:
                result.update(state='failed',error='测试进程已重启，请重试。视频会继续查询原任务。')
        result.pop('signature',None)
        result.pop('worker',None)
        if result.get('preview'): result['preview'] = f'/api/admin/probes/{id}/media'
        return jsonify(result)

    @app.post('/api/admin/probes/<id>/retry')
    def retry_probe(id):
        services['require_admin']()
        kind,cfg = providers.candidate(services['body']())
        folder = probe_folder(id)
        with PROBE_LOCK:
            result = json.loads((folder/'status.json').read_text())
            if result.get('signature') != probe_signature(cfg) or result['kind'] != kind:
                raise ValueError('连接已更改，请发起新的测试。')
            if result['state'] in ('queued','running'):
                try:
                    os.kill(result.get('worker',0),0)
                except ProcessLookupError:
                    pass
                else:
                    return jsonify(id=id,state=result['state'])
            result.update(state='queued',worker=os.getpid())
            write_status(folder,result)
            PROBES.submit(execute_probe,folder,kind,cfg)
        return jsonify(id=id,state='queued')

    @app.get('/api/admin/probes/<id>/media')
    def probe_media(id):
        services['require_admin']()
        folder = probe_folder(id)
        result = json.loads((folder/'status.json').read_text())
        if result['state']!='complete' or result.get('preview') not in ('image.png','cloud-background.mp4'): abort(404)
        return send_file(folder/result['preview'])
