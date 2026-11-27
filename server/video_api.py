"""Ark-compatible async environment video, composed with the original SKU locally.

Protocol: https://github.com/volcengine/volcengine-go-sdk/blob/master/service/arkruntime/model/content_generation.go
"""
import fcntl
import hashlib
import http.client
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit, urljoin
from decimal import Decimal, InvalidOperation
from pathlib import Path
from . import model, model_admission, providers
from .store import db, model_job, now


ECONOMY_MODEL = "minimax/h3-developer/text-to-video"
ECONOMY_SECONDS = 9


def economy_config():
    """Resolve the per-task H3 choice using the current merchant service's Atlas connection."""
    cfg = model.route("video")
    if (cfg.get("protocol") != "atlas-video" or cfg.get("url") != providers.DEFAULT_URLS[("atlas", "video")]
            or not cfg.get("key")):
        raise ValueError("H3 动态背景需要已配置的 Atlas Cloud 视频连接。也可以选择本地商品运镜。")
    selected = {k: v for k, v in cfg.items() if k != "backup"}
    selected["model"] = ECONOMY_MODEL
    with db() as c:
        providers.require_catalog_model(c, selected["provider"], "video", selected)
        if model_admission.formal() and not model_admission.eligible(c, "video", selected):
            raise ValueError("H3 经济视频模型尚未通过此生产环境的模型准入。")
    return selected


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('接口发生重定向，请填写最终接口地址后再测试。')


def request_json(cfg, url, payload=None, limit=1_000_000):
    headers = {'Content-Type':'application/json', 'Accept':'application/json', 'User-Agent':'Trupic/1.0'}
    if cfg.get('protocol') == 'dashscope-video' and payload is not None:
        headers['X-DashScope-Async'] = 'enable'
    if cfg['key']:
        headers['Authorization'] = 'Bearer ' + cfg['key']
    request = urllib.request.Request(url, json.dumps(payload).encode() if payload is not None else None, headers)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=45) as response:
        raw = response.read(limit+1)
    if len(raw) > limit:
        raise ValueError('接口响应过大。')
    return json.loads(raw)


def read_with_retry(operation, *args):
    for attempt in range(3):
        try:
            return operation(*args)
        except urllib.error.HTTPError as exc:
            if attempt == 2 or exc.code not in (408, 429, 500, 502, 503, 504):
                raise
        except (OSError, http.client.IncompleteRead):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


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


def submit(cfg, prompt, ratio):
    protocol, name = cfg["protocol"], cfg["model"]
    if protocol == "dashscope-video":
        params = {"resolution":"720P", "ratio":ratio, "duration":9} if name.startswith("wan2.7") else {}
        result = request_json(cfg, cfg["url"], {"model":name, "input":{"prompt":prompt}, "parameters":params})
        return result.get("output", {}).get("task_id")
    if protocol == "atlas-video":
        payload = {"model":name, "prompt":prompt}
        if name == ECONOMY_MODEL:
            payload.update(resolution="480P", duration=ECONOMY_SECONDS, ratio=ratio, prompt_expansion=False)
        result = request_json(cfg, cfg["url"], payload)
        return result.get("data", {}).get("id")
    result = request_json(cfg, cfg["url"], dict(model=name, content=[dict(type="text",text=prompt)],
                                               duration=9, ratio=ratio, resolution="720p", generate_audio=False))
    return result.get("id")


def poll_task(cfg, task_id, receipt=None):
    if cfg["protocol"] == "dashscope-video":
        result = request_json(cfg, urljoin(cfg["url"], "/api/v1/tasks/" + task_id))["output"]
        return result["task_status"].lower(), result.get("video_url")
    if cfg["protocol"] == "atlas-video":
        result = request_json(cfg, urljoin(cfg["url"], "prediction/" + task_id))["data"]
        if result.get("id") and result["id"] != task_id:
            raise ValueError("平台返回的任务编号不匹配，请核对原视频任务。")
        if receipt is not None:
            # Only an explicitly denominated charge for this prediction is a receipt.
            # A rate, account balance, token count or missing field is never an actual charge.
            billing = result.get("billing")
            if "cost_usd" in result:
                raw, currency, field = result["cost_usd"], "USD", "cost_usd"
            elif isinstance(billing, dict):
                raw, currency, field = billing.get("amount"), billing.get("currency"), "billing.amount"
            elif result.get("charge_status") == "charged" and cfg["url"] == providers.DEFAULT_URLS["atlas", "video"]:
                raw, currency, field = result.get("price"), result.get("currency") or "USD", "price"
            else:
                raw, currency, field = None, None, None
            if raw is not None and isinstance(currency, str) and re.fullmatch("[A-Za-z]{3}", currency):
                try:
                    amount = Decimal(str(raw))
                except InvalidOperation:
                    amount = None
                if amount is not None and amount.is_finite() and amount >= 0:
                    receipt.update(amount=str(amount), currency=currency.upper(), field=field)
        urls = result.get("outputs") or []
        return result["status"].lower(), urls[0] if urls else None
    result = request_json(cfg, cfg["url"].rstrip("/") + "/" + task_id)
    return result["status"], (result.get("content") or {}).get("video_url")


def prepare_background(folder, plan, copy, cfg=None):
    primary = cfg or model.route('video')
    folder.mkdir(parents=True, exist_ok=True)
    # Different revision jobs can target the same uncommitted work/version. Concurrent
    # retries must never both read an empty checkpoint or overwrite a decoder's output.
    with (folder / ".video-task.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        job = model_job.get()
        if job:
            owned = folder / "video-jobs" / job
            original = folder / "video-task.json"
            if original.exists() and not owned.exists():
                legacy = json.loads(original.read_text())
                belongs = legacy.get("job") == job
                if "job" not in legacy:
                    with db() as c:
                        first = c.execute("""SELECT id FROM job WHERE (work,version) =
                            (SELECT work,version FROM job WHERE id=?) ORDER BY rowid LIMIT 1""", (job,)).fetchone()
                    belongs = first is not None and first[0] == job
                if belongs:
                    owned = folder
            folder = owned
        return _prepare_locked(folder, plan, copy, primary)


def _prepare_locked(folder, plan, copy, primary):
    backup = primary.get("backup")
    checkpoint = folder / 'video-task.json'
    task = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    if backup and task.get("signature") == connection_signature(backup) and task.get("state") != "failed":
        primary, backup = backup, None
    try:
        result = render_background(folder, plan, copy, primary)
        plan["videoModel"] = primary["model"]
        return result
    except (OSError, ValueError):
        # Only fail over after a confirmed rejection or terminal failure.
        if not backup or not checkpoint.exists() or json.loads(checkpoint.read_text()).get("state") != "failed":
            raise
        result = render_background(folder, plan, copy, backup)
        plan["videoModel"] = backup["model"]
        return result


def connection_signature(cfg):
    signature = hashlib.sha256((cfg['url']+'\n'+cfg['model']).encode()).hexdigest()
    return signature if cfg["protocol"] == "ark-video" else hashlib.sha256((signature + cfg["protocol"]).encode()).hexdigest()

def save_checkpoint(path, value):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        try:
            json.dump(value, tmp, ensure_ascii=False)
            tmp.flush()
            os.fsync(tmp.fileno())
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise
    os.replace(tmp.name, path)
    parent = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def frame_digest(frames, count):
    paths = sorted(frames.glob("*.jpg"))
    if len(paths) != count:
        return None
    digest = hashlib.sha256()
    for index, path in enumerate(paths, 1):
        if path.name != f"{index:03d}.jpg" or not path.stat().st_size:
            return None
        with path.open("rb") as source:
            digest.update(hashlib.file_digest(source, "sha256").digest())
    return digest.hexdigest()


def render_background(folder, plan, copy, cfg):
    if cfg.get('protocol') not in ('ark-video','dashscope-video','atlas-video') or not cfg['url'] or not cfg['model']:
        raise ValueError('请配置受支持的异步文生视频连接。')
    folder.mkdir(parents=True, exist_ok=True)
    frames = folder / 'video-background'
    duration = plan["output"].get("duration", 9)
    checkpoint = folder / 'video-task.json'
    signature = connection_signature(cfg)
    task = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    if task.get("state") == "failed" and task.get("id") and cfg["model"] == ECONOMY_MODEL:
        raise ValueError("该 H3 任务已被平台终止。请核对原任务费用后，新建一份制作报价。")
    if task.get('state') in ('failed','cancelled','expired'):
        task = {}
    if task and task.get('signature') != signature:
        raise ValueError('此项已有视频任务，请恢复原视频连接后重试，以免重复提交。')
    output = plan['output']
    ratio = '16:9' if output['width'] > output['height'] else '1:1' if output['width']==output['height'] else '9:16'
    prompt = ('制作商品广告的动态空环境，不能出现商品、包装、人物、文字或商标。中心和标题区域保持低细节，轻微环境运动。'
              '商品原图、标题和字幕将随后精确合成。主题：'+plan['coordination']['product']+'。创意：'+plan['coordination']['concept']+
              '。分镜信息：'+json.dumps(copy['storyboard'],ensure_ascii=False))
    if direction := plan.get("promptBrief", {}).get("prompts", {}).get("video"):
        prompt += "。短片创作指令：" + direction
    if method := plan.get("videoReference",{}).get("method"):
        prompt += "。仅参考以下镜头衔接方法，保留商家商品与事实：" + method
    request_hash = hashlib.sha256(json.dumps(
        [prompt, output["width"], output["height"], duration], ensure_ascii=False,
    ).encode()).hexdigest()
    if task.get("requestHash") and task["requestHash"] != request_hash:
        raise ValueError("此视频任务已绑定另一份制作需求。请恢复原需求以复用此前的付费任务。")
    if task.get("state") == "complete" and task.get("framesDigest"):
        if frame_digest(frames, duration * 24) == task["framesDigest"]:
            plan["videoProviderReceipt"] = task["receipt"]
            return frames
    if not task:
        # A lost POST response must not cause a second paid submission on retry.
        model.reserve_provider_call('video')
        task = dict(signature=signature, state='submitting', requestHash=request_hash,
                    job=model_job.get(), submittedAt=now())
        save_checkpoint(checkpoint, task)
        started, ok, reason = time.monotonic(), False, None
        try:
            task_id = submit(cfg, prompt, ratio)
            if not isinstance(task_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',task_id):
                raise ValueError('视频接口未返回任务编号。')
            task.update(id=task_id,state='queued', acceptedAt=now())
            save_checkpoint(checkpoint, task)
            ok = True
        except Exception as exc:
            reason = model.failure_reason(exc)
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400,401,403,404,422,429):
                task['state'] = 'failed'
                save_checkpoint(checkpoint, task)
            raise
        finally:
            with db(True) as c:
                c.execute('INSERT INTO model_call(day,kind,platform,model,ok,ms,job,error) VALUES(?,?,?,?,?,?,current_model_job(),?)',(now()[:10],'video',cfg.get('provider','default'),cfg['model'],ok,round((time.monotonic()-started)*1000),reason))
    if not task.get('id'):
        raise ValueError('视频提交结果未知，请先在视频平台确认任务；不会自动重复提交。')
    task.update(requestHash=request_hash, job=model_job.get())
    try:
        clip = folder / 'cloud-background.mp4'
        clip_hash = None
        if task.get("clipDigest") and clip.is_file():
            with clip.open("rb") as binary:
                clip_hash = hashlib.file_digest(binary, "sha256").hexdigest()
        if not clip_hash or task.get("clipDigest") != clip_hash:
            charge = {}
            for _ in range(120):
                state, video_url = read_with_retry(poll_task, cfg, task['id'], charge)
                if state in ('failed','cancelled','canceled','expired'):
                    task['state'] = 'failed'
                    save_checkpoint(checkpoint, task)
                    raise ValueError('视频平台任务未成功，可检查模型配置后重试此项。')
                if state in ('succeeded','completed','success'):
                    if not isinstance(video_url, str) or not video_url:
                        raise ValueError('任务已完成但缺少下载地址，可稍后继续查询。')
                    break
                time.sleep(2)
            else:
                raise ValueError('视频仍在平台生成中。稍后重试会继续查询同一任务，不重复提交。')
            receipt = task.setdefault("receipt", {"model": cfg["model"], "predictionId": task["id"],
                                      "submittedAt": task.get("submittedAt"), "completionObservedAt": now()})
            receipt["actualCharge"] = charge or receipt.get("actualCharge")
            save_checkpoint(checkpoint, task)
            partial = folder / 'cloud-background.part'
            read_with_retry(download, video_url, partial)
            partial.replace(clip)
            with clip.open("rb") as binary:
                task["clipDigest"] = hashlib.file_digest(binary, "sha256").hexdigest()
            save_checkpoint(checkpoint, task)
        timing = "fps=24,tpad=stop_mode=clone:stop_duration=9"
        if duration != 9:
            probe = subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(clip)], timeout=15)
            length = float(probe)
            if not 0 < length < 3600:
                raise ValueError("无法核对动态背景的时长。")
            timing = f"setpts={duration / length}*(PTS-STARTPTS),fps=24,tpad=stop_mode=clone:stop_duration=1"

        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            decoded = Path(temporary) / "new"
            decoded.mkdir()
            scale = (f"scale={output['width']}:{output['height']}:force_original_aspect_ratio=increase,"
                     f"crop={output['width']}:{output['height']},{timing}")
            subprocess.run(["ffmpeg","-v","error","-i",str(clip),"-an","-vf",scale,"-t",str(duration),
                            "-q:v","2",str(decoded/"%03d.jpg")],check=True,capture_output=True,timeout=90)
            digest = frame_digest(decoded, duration * 24)
            if not digest:
                raise ValueError('视频未完整解码。')
            if frames.exists():
                frames.rename(Path(temporary) / "old")
            decoded.rename(frames)
        task.update(state="complete", framesDigest=digest)
        save_checkpoint(checkpoint, task)
        plan["videoProviderReceipt"] = task["receipt"]
        return frames
    except (OSError,http.client.IncompleteRead,KeyError,TypeError,subprocess.SubprocessError) as exc:
        raise ValueError('视频查询或下载未完成，重试会继续查询同一任务。') from exc
