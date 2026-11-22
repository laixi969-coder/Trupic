"""Ark-compatible async environment video, composed with the original SKU locally.

Protocol: https://github.com/volcengine/volcengine-go-sdk/blob/master/service/arkruntime/model/content_generation.go
"""
import hashlib
import json
import re
import subprocess
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from . import model
from .store import db, now


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('接口发生重定向，请填写最终接口地址后再测试。')


def request_json(cfg, url, payload=None, limit=1_000_000):
    headers = {'Content-Type':'application/json'}
    if cfg['key']:
        headers['Authorization'] = 'Bearer ' + cfg['key']
    request = urllib.request.Request(url, json.dumps(payload).encode() if payload is not None else None, headers)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=45) as response:
        raw = response.read(limit+1)
    if len(raw) > limit:
        raise ValueError('接口响应过大。')
    return json.loads(raw)


def download(url, path):
    endpoint = urlsplit(url)
    if endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password:
        raise ValueError('视频结果不是有效 HTTPS 下载地址。')
    # Do not forward provider credentials to the asset CDN.
    with urllib.request.urlopen(url, timeout=90) as response, path.open('wb') as output:
        total = 0
        while block := response.read(1024 * 1024):
            total += len(block)
            if total > 100 * 1024 * 1024:
                raise ValueError('视频文件超过 100 MB。')
            output.write(block)


def prepare_background(folder, plan, copy, cfg=None):
    cfg = cfg or model.route('video')
    if cfg.get('protocol') != 'ark-video' or not cfg['url'] or not cfg['model']:
        raise ValueError('请配置支持方舟任务协议的视频模型。')
    folder.mkdir(parents=True, exist_ok=True)
    frames = folder / 'video-background'
    if (frames / '216.jpg').is_file():
        return frames
    checkpoint = folder / 'video-task.json'
    signature = hashlib.sha256((cfg['url']+'\n'+cfg['model']).encode()).hexdigest()
    task = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    if task.get('state') in ('failed','cancelled','expired'):
        task = {}
    if task and task.get('signature') != signature:
        raise ValueError('此项已有视频任务，请恢复原视频连接后重试，以免重复提交。')
    output = plan['output']
    ratio = '16:9' if output['width'] > output['height'] else '1:1' if output['width']==output['height'] else '9:16'
    prompt = ('制作商品广告的动态空环境，不能出现商品、包装、人物、文字或商标。中心和标题区域保持低细节，轻微环境运动。'
              '商品原图、标题和字幕将随后精确合成。主题：'+plan['coordination']['product']+'。创意：'+plan['coordination']['concept']+
              '。分镜信息：'+json.dumps(copy['storyboard'],ensure_ascii=False))
    if not task:
        # A lost POST response must not cause a second paid submission on retry.
        model.reserve_provider_call('video')
        task = dict(signature=signature,state='submitting')
        checkpoint.write_text(json.dumps(task))
        started, ok = time.monotonic(), False
        try:
            result = request_json(cfg,cfg['url'],dict(model=cfg['model'],content=[dict(type='text',text=prompt)],duration=9,ratio=ratio,resolution='720p',generate_audio=False))
            task_id = result.get('id')
            if not isinstance(task_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',task_id):
                raise ValueError('视频接口未返回任务编号。')
            task.update(id=task_id,state='queued')
            checkpoint.write_text(json.dumps(task))
            ok = True
        except urllib.error.HTTPError as exc:
            if exc.code in (400,401,403,404,422,429):
                task['state'] = 'failed'
                checkpoint.write_text(json.dumps(task))
            raise
        finally:
            with db(True) as c:
                c.execute('INSERT INTO model_call(day,kind,platform,model,ok,ms) VALUES(?,?,?,?,?,?)',(now()[:10],'video',cfg.get('provider','default'),cfg['model'],ok,round((time.monotonic()-started)*1000)))
    if not task.get('id'):
        raise ValueError('视频提交结果未知，请先在视频平台确认任务；不会自动重复提交。')
    try:
        for _ in range(120):
            result = request_json(cfg,cfg['url'].rstrip('/')+'/'+task['id'])
            state = result.get('status')
            if state in ('failed','cancelled','expired'):
                task['state'] = state
                checkpoint.write_text(json.dumps(task))
                raise ValueError('视频平台任务未成功，可检查模型配置后重试此项。')
            if state == 'succeeded':
                break
            time.sleep(2)
        else:
            raise ValueError('视频仍在平台生成中。稍后重试会继续查询同一任务，不重复提交。')
        clip = folder / 'cloud-background.mp4'
        download(result['content']['video_url'],clip)
        frames.mkdir(exist_ok=True)
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(clip),'-an','-vf',f"scale={output['width']}:{output['height']}:force_original_aspect_ratio=increase,crop={output['width']}:{output['height']},fps=24,tpad=stop_mode=clone:stop_duration=9",'-t','9','-q:v','2',str(frames/'%03d.jpg')],check=True,capture_output=True,timeout=90)
        if not (frames/'216.jpg').is_file():
            raise ValueError('视频未完整解码。')
        return frames
    except (OSError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        raise ValueError('视频查询或下载未完成，重试会继续查询同一任务。') from exc
