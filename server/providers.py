"""Independent capability connections, compatible protocols and provider routing."""

import hashlib
import json
import re
from urllib.parse import urlsplit
from .store import audit, db

PRESETS = {
    "atlas": ("Atlas Cloud", "https://api.atlascloud.ai/v1/chat/completions"),
    "ark": (
        "火山引擎方舟",
        "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
    ),
    "bailian": (
        "阿里云百炼",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    ),
    "deepseek": ("DeepSeek", "https://api.deepseek.com/chat/completions"),
    "local": ("本机视觉模型", "http://127.0.0.1:7395/v1/chat/completions"),
    "custom": ("其他兼容平台", ""),
}
KINDS = ("text", "vision", "image", "video")
# This is the capability scope of our adapters, not a promise about every model
# hosted by a vendor. Custom connections still require an explicit capability.
SUPPORTED = {"deepseek": ("text",), "local": ("text", "vision"), "bailian": KINDS, "atlas": KINDS, "ark": KINDS, "custom": KINDS}
PROTOCOLS = {"text": ("chat",), "vision": ("chat",), "image": ("images",), "video": ("ark-video","dashscope-video","atlas-video")}
DEFAULT_VIDEO = {"ark":"ark-video", "bailian":"dashscope-video", "atlas":"atlas-video"}
DEFAULT_URLS = {("atlas","video"): "https://api.atlascloud.ai/api/v1/model/generateVideo", ("bailian","video"): "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis", ("ark", "image"): "https://ark.cn-beijing.volces.com/api/v3/images/generations", ("ark", "video"): "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"}


def supported(platform):
    return SUPPORTED.get(platform, KINDS)


def protocols_for(platform, kind):
    if kind == "video" and platform in DEFAULT_VIDEO:
        return (DEFAULT_VIDEO[platform],)
    return PROTOCOLS[kind]


def capability(record, kind):
    explicit = json.loads(record.get("connections") or "{}")
    if kind in explicit:
        return explicit[kind] if explicit[kind].get("model") else None
    if kind in ("text", "vision") and record.get(kind):
        return dict(url=record["url"], key=record["key"], model=record[kind], protocol="chat")
    return None


def save_capability(c, actor, payload):
    platform, kind = payload.get("id"), payload.get("capability")
    if not isinstance(platform, str) or (platform not in PRESETS and not re.fullmatch(r"custom-[0-9a-f]{32}", platform)):
        raise ValueError("请选择平台或新增兼容连接。")
    if kind not in KINDS or kind not in supported(platform):
        raise ValueError("该平台当前接入方式不支持这项能力。请为该能力选择其他平台。")
    old = c.execute("SELECT * FROM model_provider WHERE id=?", (platform,)).fetchone()
    record = dict(old) if old else dict(id=platform, connections="{}")
    label = PRESETS[platform][0] if platform in PRESETS else payload.get("label", "").strip()[:60]
    if not label:
        raise ValueError("请填写平台名称。")
    def field(name, limit):
        value = payload.get(name, "")
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError("接口配置字段无效。")
        return value.strip()
    url, model, key = field("url", 1200), field("model", 180), field("key", 2400)
    protocol = payload.get("protocol", protocols_for(platform, kind)[0])
    if protocol not in protocols_for(platform, kind):
        raise ValueError("接口协议与用途不匹配。")
    if model:
        safe_url(url)
        # Known text-only model names cannot accidentally receive pictures.
        if kind != "text" and re.match(r"deepseek-(?:chat|reasoner|r1|v3)(?:$|[-.])", model, re.I):
            raise ValueError("这个 DeepSeek 模型是文本模型，请用于策划与文案。")
        previous = capability(record, kind)
        if not key and previous and previous["url"] == url and not payload.get("clearKey"):
            key = previous["key"]
        if payload.get("clearKey"):
            key = ""
        if previous and previous.get("key") and previous["url"] != url and not key and not payload.get("clearKey"):
            raise ValueError("接口地址已更改，请重新填写这项能力的密钥。")
    elif c.execute("SELECT 1 FROM model_route WHERE kind=? AND platform=?", (kind,platform)).fetchone():
        raise ValueError("该能力正在使用，请先切换调用设置，再清除模型。")
    connections = json.loads(record.get("connections") or "{}")
    models_url = field("modelsUrl", 1200)
    if models_url:
        safe_url(models_url)
        if urlsplit(models_url).netloc != urlsplit(url).netloc or urlsplit(models_url).scheme != urlsplit(url).scheme:
            raise ValueError("模型列表接口须与此能力接口同源，避免把密钥发送到其他服务。")
    connections[kind] = dict(url=url, model=model, key=key, protocol=protocol, modelsUrl=models_url)
    c.execute("""INSERT INTO model_provider(id,label,url,key,text,vision,connections) VALUES(?,?,?,'','','',?)
        ON CONFLICT(id) DO UPDATE SET label=excluded.label,connections=excluded.connections""",
        (platform,label,PRESETS.get(platform,("",""))[1],json.dumps(connections)))
    audit(c,actor,"更新独立模型连接",label+" / "+kind)



def safe_url(url):
    endpoint = urlsplit(url)
    if (
        not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
        or not (
            endpoint.scheme == "https"
            or endpoint.scheme == "http"
            and endpoint.hostname in ("localhost", "127.0.0.1", "::1")
        )
    ):
        raise ValueError("请填写完整的 HTTPS 接口地址，本机可使用 HTTP。")


def overview(c):
    records = {r["id"]: dict(r) for r in c.execute("SELECT * FROM model_provider ORDER BY rowid")}
    platforms = []
    for platform in list(PRESETS) + [key for key in records if key not in PRESETS]:
        label, url = PRESETS.get(platform, (records.get(platform, {}).get("label", ""), ""))
        record = records.get(platform, dict(id=platform, label=label, url=url, key="", text="", vision=""))
        connections = {}
        for kind in supported(platform):
            cfg = capability(record, kind) or dict(url=DEFAULT_URLS.get((platform,kind), url if kind in ("text","vision") else ""), model="",key="",protocol=protocols_for(platform, kind)[0])
            connections[kind] = {k:v for k,v in cfg.items() if k != "key"} | {"hasKey":bool(cfg.get("key"))}
            cached = c.execute("SELECT data,updated FROM model_catalog WHERE platform=? AND kind=? AND signature=?",(platform,kind,catalog_signature(cfg))).fetchone()
            if cached:
                connections[kind]["catalog"] = dict(models=json.loads(cached["data"]),updated=cached["updated"])
        platforms.append(dict(id=platform,label=label,url=record["url"],text=record.get("text",""),vision=record.get("vision",""),hasKey=bool(record.get("key")),connections=connections,supported=list(supported(platform))))
    return {"platforms": platforms, "routes": {r["kind"]:r["platform"] for r in c.execute("SELECT * FROM model_route")}, "protocols": PROTOCOLS}


def save(c, actor, payload):
    if "capability" in payload:
        return save_capability(c, actor, payload)
    platform = payload.get("id")
    if not isinstance(platform, str) or (
        platform not in PRESETS and not re.fullmatch(r"custom-[0-9a-f]{32}", platform)
    ):
        raise ValueError("请选择支持的平台。")

    def field(name, cap):
        value = payload.get(name, "")
        if not isinstance(value, str) or len(value) > cap:
            raise ValueError("平台配置字段无效。")
        return value.strip()

    label = PRESETS[platform][0] if platform in PRESETS else field("label", 60)
    if not label:
        raise ValueError("请为这个模型平台填写名称。")
    url = field("url", 1200)
    safe_url(url)
    text, vision = field("text", 180), field("vision", 180)
    if vision and "vision" not in supported(platform):
        raise ValueError("该平台当前接入方式仅支持文案，请另外配置视觉模型。")
    old = c.execute(
        "SELECT url,key FROM model_provider WHERE id=?", (platform,)
    ).fetchone()
    key = field("key", 2400)
    if not key and old and old["url"] == url and not payload.get("clearKey"):
        key = old["key"]
    if (
        not key
        and urlsplit(url).hostname not in ("localhost", "127.0.0.1", "::1")
        and (text or vision)
        and platform in PRESETS
        and platform != "custom"
        and not payload.get("clearKey")
    ):
        raise ValueError("请填写该云平台的 API 密钥。修改接口地址后需重新填写。")
    for route in c.execute(
        "SELECT kind FROM model_route WHERE platform=?", (platform,)
    ):
        if route["kind"] in ("text", "vision") and not {"text": text, "vision": vision}[route["kind"]]:
            raise ValueError("该模型正在使用，请先切换对应的调用平台。")
    c.execute(
        """INSERT INTO model_provider(id,url,key,text,vision,label) VALUES(?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET url=excluded.url,key=excluded.key,text=excluded.text,vision=excluded.vision,label=excluded.label""",
        (platform, url, key, text, vision, label),
    )
    audit(c, actor, "更新模型平台", label)


def select(c, actor, payload):
    labels = []
    for kind in KINDS:
        if kind not in payload:
            continue
        platform = payload.get(kind)
        if not isinstance(platform, str):
            raise ValueError("请选择文案与视觉审核的调用平台。")
        row = None
        if platform and platform != "local-rules":
            row = c.execute("SELECT * FROM model_provider WHERE id=?", (platform,)).fetchone()
            if kind not in supported(platform) or not row or not capability(dict(row), kind):
                raise ValueError("请先保存该平台对应能力的接口与模型。")
        labels.append(
            (row["label"] or PRESETS.get(platform,(platform,))[0]) if row else "本地处理" if platform else "默认连接"
        )
        c.execute(
            "INSERT INTO model_route VALUES(?,?) ON CONFLICT(kind) DO UPDATE SET platform=excluded.platform",
            (kind, platform),
        )
    audit(
        c,
        actor,
        "切换模型平台",
        " / ".join(labels),
    )


def connection(kind):
    if kind not in KINDS:
        raise ValueError("未知的创作能力。")
    with db() as c:
        route = c.execute("SELECT platform FROM model_route WHERE kind=?", (kind,)).fetchone()
        if route and route[0] == "local-rules":
            return dict(provider="local-rules",url="",key="",model="",protocol=PROTOCOLS[kind][0])
        row = c.execute("""SELECT p.* FROM model_route r JOIN model_provider p ON r.platform=p.id WHERE r.kind=?""", (kind,)).fetchone()
    if row:
        cfg = capability(dict(row),kind)
        if kind not in supported(row["id"]) or not cfg:
            raise ValueError("已选平台不支持此用途，请重新保存调用设置。")
        return dict(provider=row["id"], **cfg)


def catalog_signature(cfg):
    return hashlib.sha256(json.dumps([cfg.get(k,"") for k in ("url","modelsUrl","key")]).encode()).hexdigest()


def candidate(payload, require_model=True):
    platform, kind = payload.get("id"), payload.get("capability")
    if not isinstance(platform,str) or (platform not in PRESETS and not re.fullmatch(r"custom-[0-9a-f]{32}",platform)) or kind not in KINDS or kind not in supported(platform):
        raise ValueError("请选择有效的平台与能力。")
    with db() as c:
        row = c.execute("SELECT * FROM model_provider WHERE id=?",(platform,)).fetchone()
    previous = capability(dict(row),kind) if row else None
    cfg = {}
    for key, limit in (("url",1200),("modelsUrl",1200),("model",180),("key",2400)):
        value = payload.get(key, "")
        if not isinstance(value,str) or len(value)>limit:
            raise ValueError("接口配置字段无效。")
        cfg[key] = value.strip()
    safe_url(cfg["url"])
    if not cfg["key"] and previous and previous["url"] == cfg["url"] and not payload.get("clearKey"):
        cfg["key"] = previous["key"]
    if payload.get("clearKey"):
        cfg["key"] = ""
    cfg["protocol"] = payload.get("protocol",protocols_for(platform, kind)[0])
    if cfg["protocol"] not in protocols_for(platform, kind):
        raise ValueError("接口协议与能力不匹配。")
    if require_model and not cfg["model"]:
        raise ValueError("请先填写或同步选择模型。")
    if kind != "text" and re.match(r"deepseek-(?:chat|reasoner|r1|v3)(?:$|[-.])",cfg["model"],re.I):
        raise ValueError("此模型用于文本，不支持当前用途。")
    return kind, dict(provider=platform, **cfg)
