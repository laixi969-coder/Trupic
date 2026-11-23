"""Independent capability connections, compatible protocols and provider routing."""

import hashlib
import json
import re
from urllib.parse import urlsplit
from . import model_admission
from .store import audit, db, dump, now

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
KINDS = ("text", "vision", "image", "video", "edit")
# This is the capability scope of our adapters, not a promise about every model
# hosted by a vendor. Custom connections still require an explicit capability.
SUPPORTED = {"deepseek": ("text",), "local": ("text", "vision"), "bailian": KINDS[:-1], "atlas": KINDS[:-1], "ark": KINDS[:-1], "custom": KINDS}
PROTOCOLS = {"edit": ("image-edits",), "text": ("chat",), "vision": ("chat",), "image": ("images",), "video": ("ark-video","dashscope-video","atlas-video")}
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
        cfg = explicit[kind]
        if not cfg.get("model"):
            return None
        if cfg.get("baseUrl") and urlsplit(cfg["baseUrl"]).hostname == "api.atlascloud.ai":
            resolved = resolve_base(dict(id=record["id"], capability=kind, baseUrl=cfg["baseUrl"]), None)
            return {**cfg, **{key: resolved[key] for key in ("url", "protocol", "modelsUrl")}}
        return cfg
    if kind in ("text", "vision") and record.get(kind):
        return dict(url=record["url"], key=record["key"], model=record[kind], protocol="chat")
    return None


ENDPOINT_SUFFIX = {
    "chat": "/chat/completions",
    "images": "/images/generations",
    "image-edits": "/images/edits",
    "ark-video": "/contents/generations/tasks",
    "dashscope-video": "/services/aigc/video-generation/video-synthesis",
    "atlas-video": "/model/generateVideo",
}


def connection_base(cfg):
    return cfg.get("baseUrl") or cfg["url"].rstrip("/").removesuffix(ENDPOINT_SUFFIX[cfg["protocol"]])


def resolve_base(payload, previous):
    """Expand the simple form for the existing save, discovery and probe paths."""
    if "baseUrl" not in payload:
        return payload
    base = payload["baseUrl"]
    if not isinstance(base, str) or len(base) > 1200:
        raise ValueError("Base URL 无效。")
    base = base.strip().rstrip("/")
    safe_url(base)
    platform, kind = payload["id"], payload["capability"]
    protocol = protocols_for(platform, kind)[0]
    parts = urlsplit(base)
    if parts.hostname == "api.atlascloud.ai" and parts.path in ("", "/v1", "/api/v1"):
        protocol = "atlas-video" if kind == "video" else PROTOCOLS[kind][0]
        root = parts._replace(path="/api/v1" if kind == "video" else "/v1").geturl()
        return {**payload, "baseUrl": base, "url": root + ENDPOINT_SUFFIX[protocol],
                "protocol": protocol, "modelsUrl": ""}
    if previous and base == connection_base(previous):
        return {**payload, "baseUrl": base, "url": previous["url"],
                "protocol": previous["protocol"], "modelsUrl": previous.get("modelsUrl", "")}
    parts = urlsplit(base)
    host = parts.hostname
    if kind == "video" and platform.startswith("custom"):
        if host == "api.atlascloud.ai":
            protocol = "atlas-video"
        elif host.endswith(".maas.aliyuncs.com") or (host.startswith("dashscope") and host.endswith(".aliyuncs.com")):
            protocol = "dashscope-video"
        elif previous:
            protocol = previous["protocol"]
    root = base
    if protocol in ("atlas-video", "dashscope-video") and not root.endswith("/api/v1"):
        path = parts.path.removesuffix("/compatible-mode/v1").removesuffix("/v1")
        root = parts._replace(path=path + "/api/v1").geturl()
    return {**payload, "baseUrl": base, "url": root + ENDPOINT_SUFFIX[protocol],
            "protocol": protocol, "modelsUrl": ""}


def editable_connection(record, kind):
    """Reuse a saved platform connection when configuring another capability."""
    current = capability(record, kind)
    if current:
        return current
    for source_kind in supported(record["id"]):
        source = capability(record, source_kind)
        if source and source.get("baseUrl"):
            resolved = resolve_base(dict(id=record["id"], capability=kind,
                                         baseUrl=source["baseUrl"]), None)
            return dict(url=resolved["url"], baseUrl=source["baseUrl"],
                        protocol=resolved["protocol"], modelsUrl=source.get("modelsUrl", ""),
                        key=source["key"], model="")
    return None


def cached_catalog(c, platform, kind, cfg):
    from .model_tools import models_endpoint

    rows = c.execute("SELECT * FROM model_catalog WHERE platform=? ORDER BY updated DESC",
                     (platform,)).fetchall()
    record = c.execute("SELECT * FROM model_provider WHERE id=?", (platform,)).fetchone()
    for row in rows:
        if row["kind"] == kind and row["signature"] == catalog_signature(cfg):
            return row
        source = capability(dict(record), row["kind"]) if record else None
        if not source or source.get("key") != cfg.get("key"):
            continue
        try:
            same_catalog = models_endpoint(source) == models_endpoint(cfg)
        except ValueError:
            continue
        if same_catalog and row["signature"] == catalog_signature(source):
            return row
    return None


def save_capability(c, actor, payload):
    platform, kind = payload.get("id"), payload.get("capability")
    if not isinstance(platform, str) or (platform not in PRESETS and not re.fullmatch(r"custom-[0-9a-f]{32}", platform)):
        raise ValueError("请选择平台或新增兼容连接。")
    if kind not in KINDS or kind not in supported(platform):
        raise ValueError("该平台当前接入方式不支持这项能力。请为该能力选择其他平台。")
    old = c.execute("SELECT * FROM model_provider WHERE id=?", (platform,)).fetchone()
    record = dict(old) if old else dict(id=platform, connections="{}")
    previous = editable_connection(record, kind) if "baseUrl" in payload else capability(record, kind)
    payload = resolve_base(payload, previous)
    label = PRESETS[platform][0] if platform in PRESETS else payload.get("label", "").strip()[:60]
    if not label and payload.get("baseUrl"):
        label = record.get("label") or urlsplit(payload["baseUrl"]).hostname[:60]
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
    if "baseUrl" in payload:
        require_catalog_model(c, platform, kind, connections[kind])
        connections[kind]["baseUrl"] = payload["baseUrl"]
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


def route_snapshot(c):
    snapshot = {}
    for kind in KINDS:
        picks = {}
        for key, table in (("primary", "model_route"), ("backup", "model_backup")):
            row = c.execute(
                f"SELECT platform FROM {table} WHERE kind=?", (kind,)
            ).fetchone()
            platform = row[0] if row else ""
            provider = c.execute(
                "SELECT * FROM model_provider WHERE id=?", (platform,)
            ).fetchone()
            cfg = capability(dict(provider), kind) if provider else {}
            picks[key] = {"platform": platform, "model": (cfg or {}).get("model", "")}
        snapshot[kind] = picks
    return snapshot


def route_version(c):
    return c.execute("SELECT COALESCE(MAX(n),0) FROM model_route_version").fetchone()[0]


def overview(c):
    records = {
        r["id"]: dict(r)
        for r in c.execute("SELECT * FROM model_provider ORDER BY rowid")
    }
    platforms = []
    for platform in list(PRESETS) + [key for key in records if key not in PRESETS]:
        label, url = PRESETS.get(platform, (records.get(platform, {}).get("label", ""), ""))
        record = records.get(platform, dict(id=platform, label=label, url=url, key="", text="", vision=""))
        connections = {}
        for kind in supported(platform):
            cfg = editable_connection(record, kind) or dict(url=DEFAULT_URLS.get((platform,kind), url if kind in ("text","vision") else ""), model="",key="",protocol=protocols_for(platform, kind)[0])
            connections[kind] = {k:v for k,v in cfg.items() if k != "key"} | {"hasKey":bool(cfg.get("key"))}
            connections[kind]["baseUrl"] = connection_base(cfg) or url.removesuffix(ENDPOINT_SUFFIX["chat"])
            cached = cached_catalog(c, platform, kind, cfg)
            candidate_cfg = {**cfg, "provider":platform}
            connections[kind]["approved"] = bool(cfg.get("model") and model_admission.eligible(c,kind,candidate_cfg))
            if cached:
                connections[kind]["catalog"] = dict(models=json.loads(cached["data"]),updated=cached["updated"])
        platforms.append(dict(id=platform,label=label,url=record["url"],text=record.get("text",""),vision=record.get("vision",""),hasKey=bool(record.get("key")),connections=connections,supported=list(supported(platform))))
    return {"routeVersion": route_version(c), "formal": model_admission.formal(), "platforms": platforms, "backups": {r["kind"]:r["platform"] for r in c.execute("SELECT * FROM model_backup")}, "routes": {r["kind"]:r["platform"] for r in c.execute("SELECT * FROM model_route")}, "protocols": PROTOCOLS}


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


def select(c, actor, payload, before=None):
    version = route_version(c)
    if "expectedVersion" in payload and payload["expectedVersion"] != version:
        raise ValueError("模型路由已变更，请刷新并核对后再保存。")
    if before is None:
        before = route_snapshot(c)
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
            if model_admission.formal() and not model_admission.eligible(c,kind,{"provider":platform, **capability(dict(row),kind)}):
                raise ValueError("正式调用需要核验发布日期、系列版本和测试记录。")
        labels.append(
            (row["label"] or PRESETS.get(platform,(platform,))[0]) if row else "本地处理" if platform else "默认连接"
        )
        c.execute(
            "INSERT INTO model_route VALUES(?,?) ON CONFLICT(kind) DO UPDATE SET platform=excluded.platform",
            (kind, platform),
        )
    backups = payload.get("backups", {})
    if not isinstance(backups, dict) or set(backups) - set(KINDS):
        raise ValueError("备用连接配置无效。")
    for kind in KINDS:
        primary = c.execute("SELECT platform FROM model_route WHERE kind=?", (kind,)).fetchone()
        if kind not in backups and kind in payload:
            c.execute("DELETE FROM model_backup WHERE kind=? AND (platform=? OR ? IN ('','local-rules'))",
                      (kind,payload[kind],payload[kind]))
        if kind not in backups:
            continue
        platform = backups[kind]
        if platform:
            if not isinstance(platform,str) or not primary or primary[0] in ("","local-rules",platform):
                raise ValueError("备用连接须与已保存的主连接不同。")
            if not checked_connection(c, kind, platform):
                raise ValueError("备用连接缺少可用模型或正式核验。")
            c.execute("INSERT OR REPLACE INTO model_backup VALUES(?,?)", (kind,platform))
        else:
            c.execute("DELETE FROM model_backup WHERE kind=?", (kind,))
    after = route_snapshot(c)
    if before != after:
        c.execute("INSERT INTO model_route_version VALUES(?,?,?,?,?)",
                  (version + 1, actor, now(), dump(before), dump(after)))
    labels.append(json.dumps(backups,ensure_ascii=False))
    audit(
        c,
        actor,
        "切换模型平台",
        " / ".join(labels),
    )


def checked_connection(c, kind, platform):
    row = c.execute("SELECT * FROM model_provider WHERE id=?", (platform,)).fetchone()
    cfg = capability(dict(row),kind) if row and kind in supported(platform) else None
    if cfg:
        cfg = dict(provider=platform, **cfg)
        if not model_admission.formal() or model_admission.eligible(c,kind,cfg):
            return cfg


def connection(kind):
    if kind not in KINDS:
        raise ValueError("未知的创作能力。")
    with db() as c:
        route = c.execute("SELECT platform FROM model_route WHERE kind=?", (kind,)).fetchone()
        if not route or not route[0]:
            return None
        if route[0] != "local-rules":
            primary = checked_connection(c, kind, route[0])
            backup_id = c.execute("SELECT platform FROM model_backup WHERE kind=?", (kind,)).fetchone()
            backup = checked_connection(c, kind, backup_id[0]) if backup_id else None
            if primary:
                if backup:
                    primary["backup"] = backup
                return primary
            if backup:
                return backup
        return dict(provider="local-rules",url="",key="",model="",protocol=PROTOCOLS[kind][0])


def catalog_signature(cfg):
    return hashlib.sha256(json.dumps([cfg.get(k,"") for k in ("url","modelsUrl","key")]).encode()).hexdigest()


def require_catalog_model(c, platform, kind, cfg):
    row = cached_catalog(c, platform, kind, cfg)
    if not row or not any(m["id"] == cfg["model"] and (not m["known"] or kind in m["kinds"])
                          for m in json.loads(row["data"])):
        raise ValueError("请同步当前连接的最新模型并从列表中选择。")


def candidate(payload, require_model=True):
    platform, kind = payload.get("id"), payload.get("capability")
    if not isinstance(platform,str) or (platform not in PRESETS and not re.fullmatch(r"custom-[0-9a-f]{32}",platform)) or kind not in KINDS or kind not in supported(platform):
        raise ValueError("请选择有效的平台与能力。")
    with db() as c:
        row = c.execute("SELECT * FROM model_provider WHERE id=?",(platform,)).fetchone()
    previous = (editable_connection(dict(row), kind) if "baseUrl" in payload else capability(dict(row), kind)) if row else None
    payload = resolve_base(payload, previous)
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
        raise ValueError("请先同步模型并选择一个模型。")
    if kind != "text" and re.match(r"deepseek-(?:chat|reasoner|r1|v3)(?:$|[-.])",cfg["model"],re.I):
        raise ValueError("此模型用于文本，不支持当前用途。")
    if require_model and "baseUrl" in payload:
        with db() as c:
            require_catalog_model(c, platform, kind, cfg)
    return kind, dict(provider=platform, **cfg)
