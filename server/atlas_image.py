"""Generate an Atlas image and resume the same prediction after a poll/download failure."""
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .model import reserve_provider_call
from .video_api import NoRedirect, request_json

ROOT = "https://api.atlascloud.ai/api/v1/model"


def matches(cfg):
    return urlsplit(cfg["url"]).hostname == "api.atlascloud.ai"


def generate(cfg, folder, prompt, width, height):
    payload = dict(model=cfg["model"], prompt=prompt)
    if cfg["model"] == "bytedance/seedream-v5.5/text-to-image":
        sizes = [(2048, 2048), (2368, 1776), (1776, 2368), (2816, 1584), (1584, 2816),
                 (2496, 1664), (1664, 2496), (3136, 1344)]
        w, h = min(sizes, key=lambda size: abs(size[0] / size[1] - width / height))
        payload["size"] = f"{w}*{h}"
    folder.mkdir(parents=True, exist_ok=True)
    signature = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    checkpoint = folder / f"atlas-image-{signature}.json"
    try:
        if checkpoint.exists():
            task_id = json.loads(checkpoint.read_text())
        else:
            reserve_provider_call("image")
            result = request_json(cfg, ROOT + "/generateImage", payload)
            task = result.get("data") or result
            task_id = task.get("id")
            if not isinstance(task_id, str) or not re.fullmatch(r"[\w-]{1,160}", task_id):
                raise ValueError("Atlas 未接受图片任务，请核对模型和账户额度。")
            tmp = checkpoint.with_suffix(".tmp")
            tmp.write_text(json.dumps(task_id))
            tmp.replace(checkpoint)
        for _ in range(120):
            result = request_json(cfg, ROOT + "/prediction/" + task_id)
            task = result.get("data") or result
            state = str(task.get("status", "")).lower()
            if state in ("failed", "cancelled", "canceled", "expired"):
                checkpoint.unlink(missing_ok=True)
                raise ValueError("Atlas 图片生成任务失败，请在平台查看任务 " + task_id + "。")
            if state in ("completed", "succeeded", "success"):
                outputs = task.get("outputs") or []
                if not outputs or not isinstance(outputs[0], str) or urlsplit(outputs[0]).scheme != "https":
                    raise ValueError("Atlas 已完成图片任务，但未返回图片下载地址。")
                request = urllib.request.Request(outputs[0], headers={"User-Agent":"Trupic/1.0"})
                with urllib.request.build_opener(NoRedirect()).open(request, timeout=90) as response:
                    data = response.read(24_000_001)
                if len(data) > 24_000_000:
                    raise ValueError("Atlas 返回的图片超过大小限制。")
                return data
            time.sleep(2)
        raise ValueError("Atlas 图片仍在生成。重试会继续查询同一任务。")
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Atlas 图片服务返回 HTTP {exc.code}。") from exc
    except OSError as exc:
        if checkpoint.exists():
            raise ValueError("与 Atlas 的连接中断，重试会继续获取同一张图片。") from exc
        raise ValueError("未收到 Atlas 图片提交结果，请在平台核对任务记录。") from exc
