"""Use licensed references for color and layout without compositing their pixels."""

import json

from PIL import Image, ImageStat
from . import model
from .media import photo_layout_features
from .store import DATA


def study(c, tenant, refs, owner):
    if refs is None:
        return []
    if not isinstance(refs, list) or len(refs) > 2:
        raise ValueError("最多可添加一张配色参考和一张构图参考。")
    result = []
    for r in refs:
        if (
            not isinstance(r, dict)
            or r.get("role") not in ("color", "layout")
            or r.get("authorized") is not True
        ):
            raise ValueError("请确认有权使用参考图，并选择参考用途。")
        role = r["role"]
        if any(existing["role"] == role for existing in result):
            raise ValueError("每种参考用途请选择一张图。")
        a = owner(c, "asset", r.get("id"), tenant)
        path = DATA / tenant / "assets" / a["id"] / "original.png"
        if role == "color":
            with Image.open(path) as image:
                image.thumbnail((128, 128))
                swatch = [round(x) for x in ImageStat.Stat(image.convert("RGB")).median]
            result.append(
                dict(
                    id=a["id"],
                    role=role,
                    source=a["name"],
                    authorized=True,
                    color=swatch,
                )
            )
        else:
            features = photo_layout_features(path)
            mode = "bleed" if features.get("calmArea", 0) > 0.45 else "framed"
            result.append(
                dict(
                    id=a["id"],
                    role=role,
                    source=a["name"],
                    authorized=True,
                    layout=mode,
                    features=features,
                )
            )
    return result


def suggest_sources(c, tenant, ids, brief, owner):
    if (
        not isinstance(ids, list)
        or not 2 <= len(ids) <= 3
        or any(not isinstance(i, str) for i in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("请选择两到三张不同的图片。")
    rows = [owner(c, "asset", i, tenant) for i in ids]
    records = [json.loads(r["info"]) for r in rows]
    valid = [i for i, info in enumerate(records) if not info["risk"]]
    if not valid:
        raise ValueError("没有清晰的商品图，请补充原片。")
    paths = [DATA / tenant / "assets" / i / "original.png" for i in ids]
    features = [photo_layout_features(path) for path in paths]
    subject = max(
        valid,
        key=lambda i: (
            records[i].get("suppliedTransparency", False),
            records[i]["file"] == "subject.png",
            features[i].get("edgeDensity", 0),
        ),
    )
    cfg = model.route("vision")
    if cfg.get("model"):
        from .visual_review import image_message

        content = [{"type": "text", "text": "商家需求：" + brief}]
        for i, path in enumerate(paths):
            with Image.open(path) as photo:
                content.extend(image_message("候选图 " + str(i + 1), photo))
        try:
            answer, _ = model.routed_chat(
                cfg,
                [
                    {
                        "role": "system",
                        "content": "请找出最清楚展示本次推广商品原物的一张图片。仅返回 JSON，product 是从 1 开始的图片序号。",
                    },
                    {"role": "user", "content": content},
                ],
                100,
                "vision",
            )
            choice = answer.get("product")
            if type(choice) is int and choice - 1 in valid:
                subject = choice - 1
        except (OSError, ValueError, KeyError, IndexError):
            pass
    remaining = [i for i in range(len(ids)) if i != subject]
    layout = max(remaining, key=lambda i: features[i].get("calmArea", 0))
    roles = {layout: "layout"}
    if len(remaining) == 2:
        roles[next(i for i in remaining if i != layout)] = "color"
    return dict(
        asset=ids[subject],
        references=[
            dict(id=ids[i], role=role, authorized=True) for i, role in roles.items()
        ],
    )


def analyze_clip(path):
    import json
    import subprocess

    source = ["-v", "error", "-protocol_whitelist", "file", "-f", "mov"]
    try:
        info = subprocess.run(
            [
                "ffprobe",
                *source,
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,codec_name:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            timeout=8,
            check=True,
        )
        metadata = json.loads(info.stdout)
        stream = metadata["streams"][0]
        duration = float(metadata["format"]["duration"])
        if not 1 <= duration <= 120 or stream["width"] * stream["height"] > 4096 * 2160:
            raise ValueError("参考视频须为 1–120 秒，画面最大支持 4K。")
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                *source,
                "-threads",
                "2",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-an",
                "-vf",
                "fps=2,scale=16:16",
                "-frames:v",
                "240",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            capture_output=True,
            timeout=20,
            check=True,
        )
    except (OSError, IndexError, KeyError, subprocess.SubprocessError) as exc:
        raise ValueError("无法读取参考视频，请使用可播放的 MP4 或 MOV。") from exc
    stride = 16 * 16 * 3
    frames = [
        result.stdout[i : i + stride]
        for i in range(0, len(result.stdout) - stride + 1, stride)
    ]
    if len(frames) < 2:
        raise ValueError("参考视频缺少连续画面。")
    changes = [
        (round(sum(abs(a - b) for a, b in zip(left, right)) / stride, 2), i / 2)
        for i, (left, right) in enumerate(zip(frames, frames[1:]), 1)
    ]
    cuts = sorted(
        t for difference, t in sorted(changes, reverse=True)[:16] if difference >= 32
    )
    analysis = dict(duration=round(duration, 3), cuts=cuts, samples=len(frames))
    cfg = model.route("vision")
    if cfg.get("model"):
        from .visual_review import image_message
        import io

        content = []
        try:
            for fraction in (0.1, 0.5, 0.9):
                sample = subprocess.run(
                    [
                        "ffmpeg",
                        "-nostdin",
                        *source,
                        "-ss",
                        str(duration * fraction),
                        "-i",
                        str(path),
                        "-map",
                        "0:v:0",
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=320:320:force_original_aspect_ratio=decrease",
                        "-f",
                        "image2pipe",
                        "-c:v",
                        "mjpeg",
                        "-",
                    ],
                    capture_output=True,
                    timeout=8,
                    check=True,
                )
                with Image.open(io.BytesIO(sample.stdout)) as frame:
                    content.extend(image_message(f"{fraction:.0%} 位置的画面", frame))
            observed, _ = model.routed_chat(
                cfg,
                [
                    {
                        "role": "system",
                        "content": "按顺序观察三帧，只用一句话概括可迁移的景别、构图及镜头衔接方法。忽略文字、商标和商品事实。返回 JSON，字段 method。",
                    },
                    {"role": "user", "content": content},
                ],
                180,
                "vision",
            )
            if isinstance(observed.get("method"), str):
                analysis["method"] = observed["method"].strip()[:200]
        except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
            pass
    return analysis


def register(app, services):
    import shutil
    from flask import jsonify, request
    from pathlib import Path
    from .store import db, dump, ident, now

    @app.post("/api/assets/suggest-sources")
    def suggest():
        tenant, params = services["reqtenant"](), services["body"]()
        if params.get("authorized") is not True:
            raise ValueError("请先确认素材使用权。")
        with db() as c:
            return jsonify(
                suggest_sources(
                    c,
                    tenant,
                    params.get("ids"),
                    services["string"](params.get("brief"), 1200),
                    services["owner"],
                )
            )

    @app.post("/api/video-references")
    def upload_clip():
        tenant = services["reqtenant"]()
        clip = request.files.get("video")
        if not clip or request.form.get("authorized") != "true":
            raise ValueError("请先确认有权使用参考视频，再选择文件。")
        clip_id = ident()
        folder = DATA / tenant / "video-references" / clip_id
        folder.mkdir(parents=True)
        try:
            path = folder / "reference.mov"
            clip.save(path)
            analysis = analyze_clip(path)
            name = Path(clip.filename or "参考视频").name[:100]
            with db(True) as c:
                from .object_storage import enqueue

                enqueue(c, folder, [path.name])
                c.execute(
                    "INSERT INTO video_reference VALUES(?,?,?,?,?)",
                    (clip_id, tenant, name, dump(analysis), now()),
                )
            return jsonify(id=clip_id, name=name, **analysis)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
