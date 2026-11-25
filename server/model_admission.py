"""Formal routing uses a reviewed model version and a successful matching probe."""

import datetime as dt
import json
import os
import re
from urllib.parse import urlsplit

from flask import jsonify
from .store import DATA, audit, db, dump


def formal():
    return os.getenv("TRUPIC_MODEL_STAGE", "internal") == "production"


def version(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{1,4}(?:\.\d{1,4}){0,3}", value
    ):
        raise ValueError("版本号请按数字段填写，例如 2.10。")
    parts = [int(s) for s in value.split(".")]
    return tuple(parts + [0] * (4 - len(parts)))


def eligible(c, kind, cfg):
    from .model_tools import probe_signature

    row = c.execute(
        """SELECT m.version,f.minimum,m.released,m.source FROM approved_model m JOIN model_family f ON
        f.family=m.family WHERE m.platform=? AND m.kind=? AND m.signature=?""",
        (cfg["provider"], kind, probe_signature(cfg)),
    ).fetchone()
    return bool(row and "2026-01-01" <= row["released"] <= dt.date.today().isoformat()
                and row["source"].startswith("https://") and version(row["version"]) >= version(row["minimum"]))


def register(app, services):
    from .providers import candidate
    from .model_tools import probe_signature

    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS model_family(family TEXT PRIMARY KEY,minimum TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS approved_model(platform TEXT,kind TEXT,signature TEXT,family TEXT NOT NULL,
            version TEXT NOT NULL,released TEXT NOT NULL,source TEXT NOT NULL,probe TEXT NOT NULL,review TEXT NOT NULL,
            PRIMARY KEY(platform,kind,signature));
        """)

    @app.post("/api/admin/model-admission")
    def approve():
        services["require_admin"]()
        t, v = services["reqtenant"](), services["body"]()
        kind, cfg = candidate(v)
        released = services["string"](v.get("released"), 10)
        if released:
            try:
                dt.date.fromisoformat(released)
            except ValueError:
                raise ValueError("发布日期格式应为 YYYY-MM-DD，也可留空。")
        if formal() and (not "2026-01-01" <= released <= dt.date.today().isoformat() or not v.get("source")):
            raise ValueError("正式路由需要核实 2026 年起的实际发布日期并登记官方发布依据。")
        family, number, minimum = (
            services["string"](v.get(k), 100) for k in ("family", "version", "minimum")
        )
        source, review = (
            services["string"](v.get("source"), 1000),
            services["string"](v.get("review"), 500),
        )
        if (
            not family
            or (source and (urlsplit(source).scheme != "https" or not urlsplit(source).hostname))
            or not review
        ):
            raise ValueError("请提供模型系列和质量及成本核验记录；发布依据选填。")
        if version(number) < version(minimum):
            raise ValueError("模型低于系列最低版本。")
        probe = services["string"](v.get("probe"), 32)
        if not re.fullmatch("[0-9a-f]{32}", probe):
            raise ValueError("请先测试当前连接。")
        file = DATA / "connection-probes" / probe / "status.json"
        record = json.loads(file.read_text()) if file.is_file() else {}
        signature = probe_signature(cfg)
        if (
            record.get("state") != "complete"
            or record.get("kind") != kind
            or record.get("signature") != signature
        ):
            raise ValueError("当前能力和连接尚未通过实际测试。")
        with db(True) as c:
            c.execute(
                "INSERT INTO model_family VALUES(?,?) ON CONFLICT(family) DO UPDATE SET minimum=excluded.minimum",
                (family, minimum),
            )
            c.execute(
                "INSERT OR REPLACE INTO approved_model VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    cfg["provider"],
                    kind,
                    signature,
                    family,
                    number,
                    released,
                    source,
                    probe,
                    review,
                ),
            )
            audit(
                c,
                t,
                "核准正式模型",
                dump(
                    dict(
                        platform=cfg["provider"],
                        model=cfg["model"],
                        kind=kind,
                        family=family,
                        version=number,
                        minimum=minimum,
                        source=source,
                        probe=probe,
                    )
                ),
            )
        return jsonify(ok=True)
