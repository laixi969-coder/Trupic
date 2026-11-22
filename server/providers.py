"""Named Chat Completions connections and independent routing for text and vision."""

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
KINDS = ("text", "vision")


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
    records = {
        r["id"]: dict(r)
        for r in c.execute(
            "SELECT id,label,url,text,vision,key<>'' AS hasKey FROM model_provider ORDER BY rowid"
        )
    }
    return {
        "platforms": [
            {
                "id": id,
                "url": url,
                "text": "",
                "vision": "",
                "hasKey": False,
                **records.get(id, {}),
                "label": label,
            }
            for id, (label, url) in PRESETS.items()
        ]
        + [row for id, row in records.items() if id not in PRESETS],
        "routes": {
            r["kind"]: r["platform"] for r in c.execute("SELECT * FROM model_route")
        },
    }


def save(c, actor, payload):
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
        if not {"text": text, "vision": vision}[route["kind"]]:
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
        platform = payload.get(kind)
        if not isinstance(platform, str):
            raise ValueError("请选择文案与视觉审核的调用平台。")
        if platform:
            row = c.execute(
                "SELECT text,vision,label FROM model_provider WHERE id=?", (platform,)
            ).fetchone()
            if not row or not row[kind]:
                raise ValueError("请先保存该平台对应的模型名称。")
        labels.append(
            (row["label"] or PRESETS[platform][0]) if platform else "默认连接"
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
    with db() as c:
        row = c.execute(
            """SELECT p.* FROM model_route r JOIN model_provider p ON r.platform=p.id
                        WHERE r.kind=?""",
            (kind,),
        ).fetchone()
    if row:
        return {
            "provider": row["id"],
            "url": row["url"],
            "key": row["key"],
            "model": row[kind],
        }
