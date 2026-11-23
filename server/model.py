"""Optional model inference. The application remains usable with offline creative rules."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request

from .store import DATA, db, now
from . import providers, costs

SETTINGS = DATA / "integrations.json"


ENV_NAMES = {
    "url": "TRUPIC_MODEL_URL",
    "imageUrl": "TRUPIC_IMAGE_URL",
    "imageModel": "TRUPIC_IMAGE_MODEL",
    "visionModel": "TRUPIC_VISION_MODEL",
    "visionUrl": "TRUPIC_VISION_URL",
    "visionKey": "TRUPIC_VISION_KEY",
    "imageKey": "TRUPIC_IMAGE_KEY",
    "model": "TRUPIC_MODEL",
    "key": "TRUPIC_MODEL_KEY",
    "feed": "TRUPIC_REFERENCE_FEED",
    "license": "TRUPIC_FEED_LICENSE",
    "board": "TRUPIC_PINTEREST_BOARD",
    "pinToken": "TRUPIC_PINTEREST_TOKEN",
    "pinRights": "TRUPIC_PINTEREST_LICENSE",
}


def saved_settings():
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def settings():
    data = saved_settings()
    return {k: os.environ.get(v, data.get(k, "")) for k, v in ENV_NAMES.items()}


def save_settings(data):
    previous = saved_settings()
    data = dict(data)
    for field, variable in ENV_NAMES.items():
        if variable in os.environ:
            if field in previous:
                data[field] = previous[field]
            else:
                data.pop(field, None)
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


def route(kind):
    named = providers.connection(kind)
    if named:
        return named
    if providers.model_admission.formal():
        return dict(provider="local-rules",url="",key="",model="",protocol=providers.PROTOCOLS[kind][0])
    return default_connection(kind)


def default_connection(kind):
    cfg = settings()
    if kind in ("image", "video"):
        prefix = kind
        return {"url": cfg.get(prefix + "Url", ""), "key": cfg.get(prefix + "Key", ""), "model": cfg.get(prefix + "Model", ""), "provider": "default", "protocol": "images" if kind == "image" else "ark-video"}
    if kind == "vision":
        return {
            "url": cfg["visionUrl"] or cfg["url"],
            "key": cfg["visionKey"] if cfg["visionUrl"] else cfg["key"],
            "model": cfg["visionModel"],
            "provider": "default",
        }
    return {**cfg, "provider": "default"}


def engine_name():
    cfg = route("text")
    if cfg["url"] and cfg["model"]:
        return cfg["model"]
    return "Apple 设备端模型" if cfg.get("provider") != "local-rules" and apple_available() else "本地创意规则"


def reserve_provider_call(kind):
    """Count outgoing attempts because a timed-out call may still be billable."""
    limit = os.getenv("TRUPIC_DAILY_" + kind.upper() + "_CALLS")
    cap = int(limit) if limit else None
    day = now()[:10]
    with db(True) as c:
        row = c.execute(
            "SELECT calls FROM provider_usage WHERE day=? AND kind=?", (day, kind)
        ).fetchone()
        if cap is not None and (row[0] if row else 0) >= cap:
            raise ValueError("已达当日外部服务调用上限。")
        costs.reserve(c, day, kind)
        c.execute(
            """INSERT INTO provider_usage VALUES(?,?,1)
               ON CONFLICT(day,kind) DO UPDATE SET calls=calls+1""",
            (day, kind),
        )


def ask(instructions, payload, max_tokens=650):
    cfg = route("text")
    text = json.dumps(payload, ensure_ascii=False)
    if cfg["url"] and cfg["model"]:
        return chat_request(
            cfg,
            cfg["model"],
            [
                {"role": "system", "content": instructions},
                {"role": "user", "content": text},
            ],
            max_tokens,
            "text",
        ), cfg["model"]
    elif cfg.get("provider") != "local-rules" and apple_available():
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
    return response_object(raw), name


class InvalidModelOutput(ValueError):
    """The service responded, but its generated content failed validation."""


def response_object(raw):
    if not isinstance(raw, str):
        raise InvalidModelOutput("模型未返回有效对象。")
    try:
        obj = json.loads(re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip()))
    except json.JSONDecodeError as exc:
        raise InvalidModelOutput("模型生成的内容不是有效 JSON。") from exc
    if not isinstance(obj, dict):
        raise InvalidModelOutput("模型未返回有效对象。")
    return obj


def chat_request(cfg, name, messages, max_tokens, kind):
    data = {"model": name, "messages": messages, "max_tokens": max_tokens}
    if schema := cfg.get("responseSchema"):
        data["response_format"] = {"type": "json_schema", "json_schema": {"name": "visual_audit", "schema": schema}}
    headers = {"Content-Type": "application/json"}
    if cfg["key"]:
        headers["Authorization"] = "Bearer " + cfg["key"]
    req = urllib.request.Request(cfg["url"], json.dumps(data).encode(), headers)
    reserve_provider_call(kind)
    started = time.monotonic()
    usage = {}
    ok = False
    try:
        with urllib.request.urlopen(
            req, timeout=90 if kind == "vision" else 24
        ) as response:
            body = response.read(250_001)
        if len(body) > 250_000:
            raise ValueError("模型响应过长。")
        reply = json.loads(body)
        if isinstance(reply.get("usage"), dict):
            usage = reply["usage"]
        result = response_object(reply["choices"][0]["message"]["content"])
        ok = True
        return result
    finally:
        counts = [usage.get(k) for k in ("prompt_tokens", "completion_tokens")]
        with db(True) as c:
            c.execute(
                """INSERT INTO model_call(day,kind,platform,model,ok,ms,input_tokens,output_tokens)
                      VALUES(?,?,?,?,?,?,?,?)""",
                (
                    now()[:10],
                    kind,
                    cfg.get("provider", "default"),
                    name,
                    ok,
                    round((time.monotonic() - started) * 1000),
                    *(n if type(n) is int and 0 <= n < 2**63 else None for n in counts),
                ),
            )
