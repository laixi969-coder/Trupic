"""Optional model inference. The application remains usable with offline creative rules."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

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
    if kind == "edit":
        return dict(provider="local-rules",url="",model="",key="",protocol="image-edits")
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
    return "Apple 设备端模型" if cfg.get("provider") != "local-rules" and apple_available() else ""


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
        return routed_chat(
            cfg,
            [
                {"role": "system", "content": instructions},
                {"role": "user", "content": text},
            ],
            max_tokens,
            "text",
        )
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


def copy_failure_message(exc):
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return f"文案平台拒绝访问（HTTP {exc.code}），请检查密钥及模型权限。"
        if exc.code == 429:
            return "文案平台限制了此次调用（HTTP 429），请检查额度或稍后重试。"
        return f"文案平台返回 HTTP {exc.code}，请检查平台状态和所选模型。"
    cause = getattr(exc, "reason", exc)
    if isinstance(cause, TimeoutError):
        return "等待文案平台回复超时，请稍后重试此项。"
    if isinstance(exc, OSError):
        return "无法连接文案平台，请检查网络后重试此项。"
    return "文案调用未完成，请检查平台调用记录后重试此项。"


def vision_failure_message(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return f"视觉审核平台返回 HTTP {exc.code}。请检查视觉连接的权限、额度和平台状态。"
    if isinstance(getattr(exc, "reason", exc), TimeoutError):
        return "等待视觉审核超时，请重试此项。"
    if isinstance(exc, InvalidModelOutput):
        return f"视觉审核未完成：{exc} 请重试此项。"
    if isinstance(exc, OSError):
        return "视觉审核无法读取画面或连接平台，请重试此项。"
    return "视觉审核未取得有效结论，请检查视觉模型连接后重试此项。"


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


def routed_chat(cfg, messages, max_tokens, kind):
    try:
        result = chat_request(cfg, cfg["model"], messages, max_tokens, kind)
        return result, cfg["model"]
    except (OSError, InvalidModelOutput):
        backup = cfg.get("backup")
        if not backup:
            raise
        if "responseSchema" in cfg:
            backup = {**backup, "responseSchema": cfg["responseSchema"]}
        return chat_request(backup, backup["model"], messages, max_tokens, kind), backup["model"]


def chat_request(cfg, name, messages, max_tokens, kind):
    data = {"model": name, "messages": messages, "max_tokens": max_tokens}
    # Qwen3.8 Flash enables thinking by default. Our short JSON drafting and
    # review requests use its direct-answer mode on DashScope.
    host = urlsplit(cfg["url"]).hostname or ""
    if host in (
        "dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com",
    ):
        if kind == "text" and name == "qwen3.8-flash":
            data["enable_thinking"] = False
        elif name == "qwen3.8-omni-flash":
            data["reasoning_effort"] = "none"
    if schema := cfg.get("responseSchema"):
        data["response_format"] = {"type": "json_schema", "json_schema": {"name": "visual_audit", "schema": schema}}
    headers = {"Content-Type": "application/json", "User-Agent": "Trupic/1.0"}
    if cfg["key"]:
        headers["Authorization"] = "Bearer " + cfg["key"]
    req = urllib.request.Request(cfg["url"], json.dumps(data).encode(), headers)
    reserve_provider_call(kind)
    started = time.monotonic()
    usage = {}
    ok = False
    try:
        with urllib.request.urlopen(
            req, timeout=90
        ) as response:
            body = response.read(250_001)
        if len(body) > 250_000:
            raise ValueError("模型响应过长。")
        try:
            reply = json.loads(body)
        except ValueError as exc:
            raise InvalidModelOutput("平台回复不是有效 JSON。") from exc
        if not isinstance(reply, dict):
            raise InvalidModelOutput("模型响应不是 JSON 对象。")
        if isinstance(reply.get("usage"), dict):
            usage = reply["usage"]
        choices = reply.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise InvalidModelOutput("模型响应缺少候选结果。")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise InvalidModelOutput("模型回复达到输出上限，结果被截断。")
        message = choice.get("message")
        result = response_object(message.get("content") if isinstance(message, dict) else None)
        ok = True
        return result
    finally:
        counts = [usage.get(k) for k in ("prompt_tokens", "completion_tokens")]
        with db(True) as c:
            c.execute(
                """INSERT INTO model_call(day,kind,platform,model,ok,ms,input_tokens,output_tokens,job)
                      VALUES(?,?,?,?,?,?,?,?,current_model_job())""",
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
