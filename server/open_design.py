"""Build the editable composition used by OpenDesign and our local renderer."""

import json
import logging
import os
import shutil
import subprocess
import zipfile
from html import escape
from pathlib import Path
from PIL import Image, ImageDraw

from .film_timing import camera_tick
from .campaign_frame import camera_window
from .design_source import save_source

ROOT = Path(__file__).resolve().parents[1]
NODE_MODULES = ROOT / "node_modules"
FPS = 24
GSAP_VERSION = "3.15.1"
LOG = logging.getLogger(__name__)


def composition(folder, dims, plates, titles, shots, audio, pace, captions=(), narration=None, motion_master=False):
    folder.mkdir(parents=True)
    assets = folder / "assets"
    assets.mkdir()
    shutil.copyfile(audio, assets / "soundtrack.wav")
    if narration:
        shutil.copyfile(narration["voice"], assets / "voice.wav")
        shutil.copyfile(narration["music"], assets / "music-ducked.wav")
    gsap = NODE_MODULES / "gsap" / "dist" / "gsap.min.js"
    gsap_url = f"https://cdn.jsdelivr.net/npm/gsap@{GSAP_VERSION}/dist/gsap.min.js"
    if gsap.is_file():
        shutil.copyfile(gsap, assets / "gsap.min.js")
        gsap_url = "assets/gsap.min.js"

    width, height = dims
    duration = shots[-1]["end"]
    clips = []
    camera = {}
    if motion_master:
        clips.append(f'<video id="picture-master" class="master clip" src="assets/picture.mp4" muted playsinline '
                     f'data-start="0" data-duration="{duration}" data-track-index="0" data-volume="0"></video>')
    for index, shot in enumerate(shots, 1):
        background, foreground, title = plates[index]
        start, length = shot["start"], shot["end"] - shot["start"]
        timing = f'data-start="{start}" data-duration="{length}"'
        name = escape(shot["camera"], quote=True)
        for plane, image, track, travel in (
            ("picture", background, 0, 0.45 if foreground else 1),
            ("product", foreground, 1, 1),
        ):
            if image is None or motion_master:
                continue
            key = f"{plane}-{index}"
            image.save(assets / f"{key}.png")
            camera[key] = [
                tuple(
                    round(v + (target - v) * travel)
                    for v, target in zip((0, 0, *dims), window)
                )
                for window in (
                    camera_window(dims, index, camera_tick(frame, length * FPS), pace)
                    for frame in range(length * FPS)
                )
            ]
            clips.append(
                f'<img id="{key}" class="clip plane" {timing} data-track-index="{track}" data-track-kind="graphics" src="assets/{key}.png" alt="{name}">'
            )
        key = f"title-{index}"
        title.save(assets / f"{key}.png")
        backing_layers = []
        for rect, radius in title.info.get("titleBackings", []):
            left, top, right, bottom = rect
            patch = Image.new("RGBA", (right - left + 1, bottom - top + 1))
            ImageDraw.Draw(patch).rounded_rectangle((0, 0, right-left, bottom-top), radius=radius, fill=(20, 20, 24, 218))
            backing_layers.append((f"label-{len(backing_layers)+1}", patch, (left, top)))
        save_source(assets / f"{key}.svg", dims, backing_layers, titles[index])
        words = escape(" · ".join("".join(run[1] for run in line) for line in titles[index]), quote=True)
        clips.append(
            f'<img id="{key}" class="clip title" {timing} data-track-index="2" data-track-kind="captions" src="assets/{key}.png" alt="{words}">'
        )

    for cue, layer in captions:
        layer.save(assets / cue["layer"])
        start, end = cue["startFrame"] / FPS, cue["endFrame"] / FPS
        clips.append(
            f'<img id="{Path(cue["layer"]).stem}" class="clip title" data-start="{start}" '
            f'data-duration="{end-start}" data-track-index="3" data-track-kind="captions" '
            f'src="assets/{cue["layer"]}" alt="{escape(cue["text"], quote=True)}">'
        )
    tracks = ("voice.wav", "music-ducked.wav") if narration else ("soundtrack.wav",)
    for index, track in enumerate(tracks, 4 if narration else 3):
        clips.append(f'<audio id="{Path(track).stem}" class="clip" src="assets/{track}" data-start="0" '
                     f'data-duration="{duration}" data-track-index="{index}" data-volume="1"></audio>')
    markup = "\n    ".join(clips)
    (folder / "index.html").write_text(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="od-motion-output" content="video">
  <meta name="od-motion-audio" content="required">
  <link rel="alternate" type="video/mp4" href="video.mp4">
  <title>响指出片 Trupic</title>
  <script src="{gsap_url}"></script>
  <style>
    html, body {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; background: #000; }}
    #root {{ position: relative; width: {width}px; height: {height}px; overflow: hidden; }}
    .plane, .title {{ position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; transform-origin: 0 0; }}
    .master {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
    .title {{ z-index: 2; }}
  </style>
</head>
<body>
  <main id="root" data-composition-id="main" data-start="0" data-duration="{duration}"
    data-width="{width}" data-height="{height}" data-fps="{FPS}" data-od-motion-layout="stage">
    {markup}
  </main>
  <script id="camera-windows" type="application/json">{json.dumps(camera, separators=(",", ":"))}</script>
  <script>
    const settings = JSON.parse(document.querySelector('#camera-windows').textContent);
    const root = document.querySelector('#root');
    const width = Number(root.dataset.width), height = Number(root.dataset.height);
    const duration = Number(root.dataset.duration);
    const timeline = gsap.timeline({{ paused: true }});
    timeline.to({{ time: 0 }}, {{ time: duration, duration, ease: 'none' }}, 0);
    for (const clip of root.querySelectorAll('img.clip')) {{
      const start = Number(clip.dataset.start), length = Number(clip.dataset.duration);
      timeline.set(clip, {{ opacity: 1 }}, start);
      timeline.set(clip, {{ opacity: 0 }}, start + length);
      const windows = settings[clip.id] || [];
      windows.forEach(([left, top, right, bottom], frame) => {{
        const scaleX = width / (right - left), scaleY = height / (bottom - top);
        timeline.set(clip, {{ x: -left * scaleX, y: -top * scaleY, scaleX, scaleY }},
          start + frame * length / windows.length);
      }});
    }}
    window.__timelines = window.__timelines || {{}};
    window.__timelines.main = timeline;
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )
    write_json(folder / "hyperframes.json", {"paths": {"assets": "assets"}})
    write_json(folder / "meta.json", {"id": "trupic", "name": "响指出片 Trupic"})


def write_json(path, content):
    path.write_text(
        json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def archive_project(folder, target, video, captions, narrated=False):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=2) as archive:
        archive.write(video, "video.mp4", compress_type=zipfile.ZIP_STORED)
        files = [
            folder / name for name in ("index.html", "hyperframes.json", "meta.json")
        ]
        files.extend(sorted((folder / "assets").iterdir()))
        for file in files:
            archive.write(file, file.relative_to(folder))
        archive.writestr("captions.srt", captions)
        archive.writestr(
            "使用说明.txt",
            "解压后，在 Open Design 桌面端打开解压目录作为项目，打开 index.html 预览。video.mp4 是原始成片。\n"
            "编辑 index.html 中各片段的 data-start、data-duration、素材路径，或修改音轨 data-volume。"
            "标题图层默认使用已验收的 PNG。安装对应字体后，可编辑同名 SVG，并将标题轨道的 src 改为该 SVG。\n"
            + ("voice.wav 与 music-ducked.wav 分别控制口播和配乐。替换口播字幕时，用 captions.srt 替换 spoken PNG 轨道，保留 title 标题层。\n"
               if narrated else "可用 captions.srt 替换 PNG 字幕轨。\n")
            + "可在 Open Design 中让创作助手以当前目录（.）为合成目录重新导出 video.mp4。"
            "也可在解压目录运行 npx hyperframes@0.9.40 preview 打开时间线，"
            "再通过 npx hyperframes@0.9.40 render --fps 24 -o video.mp4 导出。\n",
        )


def render_composition(folder, output):
    mode = os.getenv("TRUPIC_VIDEO_RENDERER", "auto").strip().lower()
    if mode == "ffmpeg":
        return False
    if mode not in {"auto", "hyperframes"}:
        raise ValueError("TRUPIC_VIDEO_RENDERER 应设置为 auto、hyperframes 或 ffmpeg。")
    cli = NODE_MODULES / ".bin" / "hyperframes"
    if cli.is_file():
        try:
            subprocess.run(
                [
                    str(cli),
                    "render",
                    str(folder.resolve()),
                    "--fps",
                    str(FPS),
                    "--workers",
                    "1",
                    "--quality",
                    "draft",
                    "--crf",
                    "19",
                    "--no-best-effort",
                    "--frames-cache-dir",
                    "off",
                    "--output",
                    str(output.resolve()),
                ],
                check=True,
                capture_output=True,
                timeout=120,
                env={**os.environ, "DO_NOT_TRACK": "1"},
            )
            if output.is_file() and output.stat().st_size:
                return True
        except (OSError, subprocess.SubprocessError) as error:
            LOG.warning("HyperFrames render failed: %s", error)
    if mode == "hyperframes":
        raise ValueError(
            "HyperFrames 未能导出短片，请检查 Node.js、Chrome 和 FFmpeg 后重试。"
        )
    return False
