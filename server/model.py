"""Optional model inference. The application remains usable with offline creative rules."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request

from .store import DATA

SETTINGS = DATA / "integrations.json"


def settings():
    try:
        data = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        data = {}
    names = {
        "url": "TRUPIC_MODEL_URL",
        "imageUrl": "TRUPIC_IMAGE_URL",
        "imageModel": "TRUPIC_IMAGE_MODEL",
        "imageKey": "TRUPIC_IMAGE_KEY",
        "model": "TRUPIC_MODEL",
        "key": "TRUPIC_MODEL_KEY",
        "feed": "TRUPIC_REFERENCE_FEED",
        "license": "TRUPIC_FEED_LICENSE",
        "board": "TRUPIC_PINTEREST_BOARD",
        "pinToken": "TRUPIC_PINTEREST_TOKEN",
        "pinRights": "TRUPIC_PINTEREST_LICENSE",
    }
    return {k: os.environ.get(v, data.get(k, "")) for k, v in names.items()}


def save_settings(data):
    with tempfile.NamedTemporaryFile(mode="w", dir=DATA, delete=False) as f:
        json.dump(data, f)
        name = f.name
    os.replace(name, SETTINGS)


_fm_time = 0
_fm_ok = False


def apple_available():
    global _fm_time, _fm_ok
    if time.monotonic() - _fm_time > 120:
        _fm_time = time.monotonic()
        _fm_ok = False
        if shutil.which("fm"):
            try:
                r = subprocess.run(
                    ["fm", "models"],
                    input="",
                    text=True,
                    capture_output=True,
                    timeout=4,
                )
                _fm_ok = r.returncode == 0 and bool(
                    re.search(r"system[^\n]*\bavailable\b", r.stdout, re.I)
                )
            except (OSError, subprocess.SubprocessError):
                pass
    return _fm_ok


def engine_name():
    cfg = settings()
    if cfg["url"] and cfg["model"]:
        return cfg["model"]
    return "Apple 设备端模型" if apple_available() else "本地创意规则"


def ask(instructions, payload, max_tokens=650):
    cfg = settings()
    text = json.dumps(payload, ensure_ascii=False)
    if cfg["url"] and cfg["model"]:
        reqdata = {
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": text},
            ],
            "max_tokens": max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if cfg["key"]:
            headers["Authorization"] = "Bearer " + cfg["key"]
        req = urllib.request.Request(cfg["url"], json.dumps(reqdata).encode(), headers)
        with urllib.request.urlopen(req, timeout=24) as response:
            data = response.read(250_001)
            if len(data) > 250_000:
                raise ValueError("模型响应过长。")
            raw = json.loads(data)["choices"][0]["message"]["content"]
        name = cfg["model"]
    elif apple_available():
        r = subprocess.run(
            [
                "fm",
                "respond",
                "--model",
                "system",
                "--no-stream",
                "--instructions",
                instructions,
                "--text",
                text,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=28,
            check=True,
        )
        raw = r.stdout
        name = "Apple 设备端模型"
    else:
        raise ValueError("尚未连接可用模型。")
    obj = json.loads(re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip()))
    if not isinstance(obj, dict):
        raise ValueError("模型未返回有效对象。")
    return obj, name
