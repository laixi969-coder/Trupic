"""Render a graded clean picture and deliver independently replaceable titling and audio."""

import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .open_design import archive_project, composition, render_composition

UPSTREAM = "https://github.com/Vincentwei1021/video-shotcraft/tree/59f3e9b9e936ff2bce0e18446226d770a3f2f61f"
RECIPES = (
    ("camera/depth-layer-moves", "先交代商品和环境，主体与远景以不同速度移动。"),
    ("camera/tension-camera-moves", "先让眼睛找到细节，再向它缓慢推近。"),
    (
        "outro/logo-shrink-wordmark-lockup",
        "缓缓收回完整商品，末尾停住供阅读型号或行动信息。",
    ),
)


def encode(plates, folder, audio, dims, shots, move, titles, pace, dynamic=False):
    codec = [
        "-c:v",
        "libx264",
        "-threads",
        "2",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
    ]
    ffmpeg = ["ffmpeg", "-v", "error", "-y"]
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        tmp = Path(tmp)
        project = tmp / "trupic"
        composition(project, dims, plates, titles, shots, audio, pace)
        rendered = False if dynamic else render_composition(project, tmp / "video.mp4")
        master = tmp / "picture.mp4"
        cmd = ffmpeg + [
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{dims[0]}x{dims[1]}",
            "-r",
            "24",
            "-i",
            "pipe:0",
            *codec,
            "-crf",
            "15",
            "-g",
            "72",
            "-force_key_frames",
            "0,3,6",
            "-an",
            str(master),
        ]
        with subprocess.Popen(cmd, stdin=subprocess.PIPE) as encoder:
            try:
                for index, (bg, fg, _) in sorted(plates.items()):
                    for tick in range(72):
                        encoder.stdin.write(move(bg, fg, index, tick).tobytes())
            finally:
                encoder.stdin.close()
            if encoder.wait(timeout=120):
                raise ValueError("短片净画面编码失败。")

        if not rendered:
            render_master(master, audio, project / "assets", tmp / "video.mp4", ffmpeg, codec)
        timeline = []
        subtitles = []
        edl = ["TITLE: TRUPIC", "FCM: NON-DROP FRAME", ""]
        for i, (shot, (card, purpose)) in enumerate(zip(shots, RECIPES), 1):
            start, end = (i - 1) * 3, i * 3
            startcode, endcode = f"00:00:{start:02d}", f"00:00:{end:02d}"
            words = "\n".join(v for v in (shot.get("line"), shot.get("caption")) if v)
            subtitles.append(f"{i}\n{startcode},000 --> {endcode},000\n{words}\n")
            edl.extend(
                [
                    f"{i:03d}  PICTURE  V     C        {startcode}:00 {endcode}:00 {startcode}:00 {endcode}:00",
                    "* FROM CLIP NAME: picture.mp4",
                    "",
                ]
            )
            timeline.append(
                {
                    "shot": i,
                    "startFrame": start * 24,
                    "endFrameExclusive": end * 24,
                    "camera": shot["camera"],
                    "line": shot["line"],
                    "caption": shot.get("caption", ""),
                    "titleLayer": f"title-{i}.png",
                    "inspiration": f"{UPSTREAM}/references/shots/{card}.md",
                    "adaptation": purpose,
                    "purpose": shot.get("purpose", purpose),
                    **({"evidence": shot["evidence"]} if shot.get("evidence") else {}),
                }
            )
        with zipfile.ZipFile(
            folder / "edit.zip", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=2
        ) as archive:
            archive.write(master, "picture.mp4", compress_type=zipfile.ZIP_STORED)
            archive.write(audio, "soundtrack.wav")
            for entry in timeline:
                archive.write(project / "assets" / entry["titleLayer"], entry["titleLayer"])
            archive.writestr("captions.srt", "\n".join(subtitles))
            archive.writestr("cuts.edl", "\r\n".join(edl))
            archive.writestr(
                "timeline.json",
                json.dumps(
                    {"fps": 24, "size": dims, "shots": timeline},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            archive.writestr(
                "使用说明.txt",
                "picture.mp4 为无字无声净画面，soundtrack.wav 为九秒音轨。cuts.edl 记录三个剪辑点，各 title PNG 对齐同编号的三秒镜头。使用字幕轨改字时，可用 captions.srt 替换 PNG。timeline.json 保留逐镜说明与参考卡来源。",
            )
        if dynamic:
            # Static-source project exports would misrepresent a generated motion plate.
            (folder / "open-design.zip").unlink(missing_ok=True)
        else:
            archive_project(project, folder / "open-design.zip", tmp / "video.mp4", "\n".join(subtitles))
        (tmp / "video.mp4").replace(folder / "video.mp4")
    return "HyperFrames" if rendered else "FFmpeg"


def render_master(master, audio, assets, output, ffmpeg, codec):
    cmd = ffmpeg + ["-i", str(master), "-i", str(audio)]
    filters = []
    for n in range(3):
        cmd += ["-i", str(assets / f"title-{n + 1}.png")]
        previous = f"v{n}" if n else "0:v"
        filters.append(
            f"[{previous}][{n + 2}:v]overlay=enable='between(n,{n * 72},{(n + 1) * 72 - 1})'[v{n + 1}]"
        )
    subprocess.run(
        cmd + [
            "-filter_complex", ";".join(filters), "-map", "[v3]", "-map", "1:a",
            *codec, "-crf", "19", "-c:a", "aac", "-t", "9", "-movflags", "+faststart",
            str(output),
        ],
        check=True,
        timeout=300,
        capture_output=True,
    )
