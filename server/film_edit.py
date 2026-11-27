"""Render a graded clean picture and deliver independently replaceable titling and audio."""

import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .film_timing import frame_count
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


def encode(plates, folder, audio, dims, shots, move, titles, pace, dynamic=False, narration=None, captions=()):
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
        source_picture = narration.get("picture") if narration else None
        motion_master = bool(source_picture or (dynamic and narration))
        composition(project, dims, plates, titles, shots, audio, pace, captions, narration, motion_master)
        rendered = False if dynamic or source_picture else render_composition(project, tmp / "video.mp4")
        master = tmp / "picture.mp4"
        if source_picture:
            shutil.copyfile(source_picture, master)
        else:
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
                ",".join(str(s["start"]) for s in shots),
                "-an",
                str(master),
            ]
            with subprocess.Popen(cmd, stdin=subprocess.PIPE) as encoder:
                try:
                    for index, (bg, fg, _) in sorted(plates.items()):
                        for tick in range(frame_count(shots[index-1])):
                            encoder.stdin.write(move(bg, fg, index, tick).tobytes())
                finally:
                    encoder.stdin.close()
                if encoder.wait(timeout=120):
                    raise ValueError("短片净画面编码失败。")

        if not rendered:
            render_master(master, audio, project / "assets", tmp / "video.mp4", ffmpeg, codec, shots, captions)
        timeline = []
        subtitles = []
        edl = ["TITLE: TRUPIC", "FCM: NON-DROP FRAME", ""]
        for i, shot in enumerate(shots, 1):
            card, purpose = RECIPES[0 if i == 1 else 2 if i == len(shots) else 1]
            start, end = shot["start"], shot["end"]
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
                    **({"narration": shot["narration"], "voiceStyle": (
                        narration["shotStyles"][i-1] if "shotStyles" in narration
                        else shot.get("voiceStyle") or narration.get("style")
                    )} if narration else {}),
                    "titleLayer": f"title-{i}.png",
                    "inspiration": f"{UPSTREAM}/references/shots/{card}.md",
                    "adaptation": purpose,
                    "purpose": shot.get("purpose", purpose),
                    **({"evidence": shot["evidence"]} if shot.get("evidence") else {}),
                }
            )
        srt = narration["subtitles"].read_text(encoding="utf-8") if narration else "\n".join(subtitles)
        metadata = {"fps": 24, "size": dims, "shots": timeline}
        if narration:
            metadata.update(captions=[cue for cue, _ in captions], voiceTrack="voice.wav", musicTrack="music-ducked.wav",
                            narrator={"provider": narration["provider"], "speaker": narration["speaker"]})
        with zipfile.ZipFile(
            folder / "edit.zip", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=2
        ) as archive:
            archive.write(master, "picture.mp4", compress_type=zipfile.ZIP_STORED)
            archive.write(audio, "soundtrack.wav")
            if narration:
                archive.write(narration["voice"], "voice.wav")
                archive.write(narration["music"], "music-ducked.wav")
                for cue, _ in captions:
                    archive.write(project / "assets" / cue["layer"], cue["layer"])
            for entry in timeline:
                archive.write(project / "assets" / entry["titleLayer"], entry["titleLayer"])
            archive.writestr("captions.srt", srt)
            archive.writestr("cuts.edl", "\r\n".join(edl))
            archive.writestr(
                "timeline.json",
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            archive.writestr(
                "使用说明.txt",
                "picture.mp4 为无字无声净画面，cuts.edl 记录剪辑点，各 title PNG 对齐同编号镜头。"
                + ("voice.wav 是配音，music-ducked.wav 是已压低的配乐。两轨相加可还原 soundtrack.wav 成片混音。"
                   "captions.srt 或 spoken PNG 可作为口播字幕，任选其一。timeline.json 中 endFrame 为结束帧（不含）。"
                   if narration else "soundtrack.wav 为独立音轨。使用字幕轨改字时，可用 captions.srt 替换 PNG。")
                + "timeline.json 保留逐镜说明与参考卡来源。",
            )
        if dynamic and not motion_master:
            # Static-source project exports would misrepresent a generated motion plate.
            (folder / "open-design.zip").unlink(missing_ok=True)
        else:
            if motion_master:
                shutil.copyfile(master, project / "assets" / "picture.mp4")
            archive_project(project, folder / "open-design.zip", tmp / "video.mp4", srt, narrated=bool(narration))
        if narration:
            (folder / "captions.srt").write_text(srt, encoding="utf-8")
        (tmp / "video.mp4").replace(folder / "video.mp4")
    return "HyperFrames" if rendered else "FFmpeg"


def render_master(master, audio, assets, output, ffmpeg, codec, shots, captions=()):
    cmd = ffmpeg + ["-i", str(master), "-i", str(audio)]
    filters = []
    overlays = [(f"title-{n}.png", shot["start"] * 24, shot["end"] * 24) for n, shot in enumerate(shots, 1)]
    overlays.extend((cue["layer"], cue["startFrame"], cue["endFrame"]) for cue, _ in captions)
    for n, (filename, first, end) in enumerate(overlays):
        cmd += ["-i", str(assets / filename)]
        previous = f"v{n}" if n else "0:v"
        filters.append(
            f"[{previous}][{n + 2}:v]overlay=enable='between(n,{first},{end - 1})'[v{n + 1}]"
        )
    subprocess.run(
        cmd + [
            "-filter_complex", ";".join(filters), "-map", f"[v{len(overlays)}]", "-map", "1:a",
            *codec, "-crf", "19", "-c:a", "aac", "-t", str(shots[-1]["end"]), "-movflags", "+faststart",
            str(output),
        ],
        check=True,
        timeout=300,
        capture_output=True,
    )
