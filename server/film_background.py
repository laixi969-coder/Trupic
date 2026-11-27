"""Swap the set behind the photographed product in an already approved commercial."""

import json
import shutil
import subprocess
import zipfile
from contextlib import contextmanager

from PIL import Image, ImageDraw

from .campaign_frame import camera_window
from .film_timing import camera_tick, frame_count


def verify_archive(path, shots, output):
    try:
        with zipfile.ZipFile(path) as archive:
            timeline = json.loads(archive.read("timeline.json"))
            if (
                timeline["fps"] != 24
                or timeline["size"] != [output["width"], output["height"]]
                or [
                    (s["startFrame"], s["endFrameExclusive"], s.get("narration"))
                    for s in timeline["shots"]
                ]
                != [(s["start"] * 24, s["end"] * 24, s["narration"]) for s in shots]
                or not timeline["captions"]
                or not timeline["narrator"]
            ):
                raise ValueError("原时间线与本次逐镜定稿不一致。")
            names = [
                "picture.mp4",
                "soundtrack.wav",
                "music-ducked.wav",
                "voice.wav",
                "captions.srt",
            ]
            names.extend(f"title-{i + 1}.png" for i in range(len(shots)))
            names.extend(
                f"spoken-{i + 1}.png" for i in range(len(timeline["captions"]))
            )
            if any(not archive.getinfo(name).file_size for name in names):
                raise ValueError("原剪辑包缺少完整的声音或画面。")
            return timeline
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise ValueError("原作品缺少可复用的商品画面、字幕或分轨。") from exc


def locked_tracks(folder, path, shots, output):
    timeline = verify_archive(path, shots, output)
    with zipfile.ZipFile(path) as archive:
        for name in (
            "picture.mp4",
            "voice.wav",
            "music-ducked.wav",
            "soundtrack.wav",
            "captions.srt",
        ):
            with archive.open(name) as source, (folder / name).open("wb") as dest:
                shutil.copyfileobj(source, dest)
        titles = [
            Image.open(archive.open(f"title-{i + 1}.png")).convert("RGBA")
            for i in range(len(shots))
        ]
        captions = [
            Image.open(archive.open(f"spoken-{i + 1}.png")).convert("RGBA")
            for i in range(len(timeline["captions"]))
        ]
    styles = [s.get("voiceStyle") for s in timeline["shots"]]
    audio = dict(
        voice=folder / "voice.wav",
        music=folder / "music-ducked.wav",
        mix=folder / "soundtrack.wav",
        subtitles=folder / "captions.srt",
        cues=timeline["captions"],
        shotStyles=styles,
        style=styles[0] if len(set(styles)) == 1 else "mixed",
        **timeline["narrator"],
    )
    return audio, titles, captions


@contextmanager
def master_frames(path, size):
    """Decode sequentially so locked photograph pixels also retain their original camera move."""
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-threads",
        "1",
        "pipe:1",
    ]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as decoder:

        def read():
            packet = decoder.stdout.read(size[0] * size[1] * 3)
            if len(packet) != size[0] * size[1] * 3:
                raise ValueError("原净画面缺少预期帧。")
            return Image.frombytes("RGB", size, packet)

        try:
            yield read
            if decoder.stdout.read(1) or decoder.wait(timeout=15):
                raise ValueError("原净画面帧数与已确认的时间线不一致。")
        finally:
            decoder.stdout.close()
            if decoder.poll() is None:
                decoder.kill()


def photo_mask(size, box, source):
    if not box:
        raise ValueError("原片缺少商品位置，无法单独替换背景。")
    x, y, right, bottom = map(round, box)
    mask = Image.new("L", size)
    with Image.open(source) as product:
        if "A" in product.getbands() and product.getchannel("A").getextrema()[0] < 240:
            # Sample only the visible part, including highly magnified detail shots.
            visible = (max(0, x), max(0, y), min(size[0], right), min(size[1], bottom))
            region = tuple(
                (v - (x, y)[i % 2])
                * product.size[i % 2]
                / (right - x, bottom - y)[i % 2]
                for i, v in enumerate(visible)
            )
            alpha = product.getchannel("A").resize(
                (visible[2] - visible[0], visible[3] - visible[1]),
                Image.Resampling.BILINEAR,
                box=region,
            )
            mask.paste(alpha, visible[:2])
        else:
            ImageDraw.Draw(mask).rectangle((x, y, right - 1, bottom - 1), fill=255)
    return mask


def swap_frame(original, plate, mask, shot, index, tick, pace):
    window = camera_window(
        original.size, index, camera_tick(tick, frame_count(shot)), pace
    )
    protected = mask.crop(window).resize(original.size, Image.Resampling.BILINEAR)
    # Preserve the photographed rectangle even for opaque uploads with their own scene.
    return Image.composite(original, plate, protected)
