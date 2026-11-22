import os
import shutil
import subprocess
import tempfile
import wave
from .formats import output_spec
from pathlib import Path

import numpy as np
from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageOps,
    UnidentifiedImageError,
)

ROOT = Path(__file__).resolve().parents[1]
VISUALS = ROOT / "public" / "visuals"
Image.MAX_IMAGE_PIXELS = 32_000_000
SIZES = {
    "portrait": (1080, 1440),
    "square": (1080, 1080),
    "story": (1080, 1920),
    "feed": (1080, 1350),
    "landscape": (1920, 1080),
}
PALETTES = {
    "台球": ("#0d3332", "#eae5c8", "#e1ab50"),
    "火锅": ("#8a2f1c", "#fff1d6", "#efb64e"),
    "饮品": ("#244e33", "#f4f2d6", "#d4e986"),
    "烘焙": ("#163956", "#fcf0d6", "#dbae6b"),
    "日常护理": ("#644654", "#f6ebe7", "#dbc4a6"),
}


def inspect_upload(source, folder):
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source) as raw:
            if raw.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("请选择 JPG、PNG 或 WebP 图片。")
            if raw.width * raw.height > 32_000_000:
                raise ValueError("图片超过 3200 万像素，请先缩小。")
            original_size = raw.size
            image = ImageOps.exif_transpose(raw).convert("RGBA")
            canvas = Image.new("RGB", image.size, "white")
            canvas.paste(image, mask=image.getchannel("A"))
            image = canvas
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as e:
        raise ValueError("无法读取图片，请重新选择清晰的 JPG、PNG 或 WebP。") from e
    image.save(folder / "original.png")
    image.thumbnail((2600, 2600), Image.Resampling.LANCZOS)
    sample = ImageOps.grayscale(image)
    sample.thumbnail((512, 512))
    arr = np.asarray(sample, dtype=float)
    if min(arr.shape) < 3:
        sharpness = 0
    else:
        sharpness = float(
            np.var(
                arr[1:-1, :-2]
                + arr[1:-1, 2:]
                + arr[:-2, 1:-1]
                + arr[2:, 1:-1]
                - 4 * arr[1:-1, 1:-1]
            )
        )
    lum = float(arr.mean())
    risk = (
        min(original_size) < 220
        or sharpness < 10
        or arr.std() < 6
        or lum < 12
        or lum > 248
    )
    action = "保留原图"
    detail = "清晰度与曝光适合排版。"
    file = "original.png"
    if risk:
        action = "建议换图"
        detail = "请靠近主体，在均匀光线下对焦拍摄，确保商品、包装和标识清晰可辨。"
    elif lum < 65 or lum > 212:
        fixed = ImageEnhance.Brightness(image).enhance(min(1.25, max(0.86, 130 / lum)))
        fixed.save(folder / "adjusted.png")
        file = "adjusted.png"
        action = "轻度调光"
        detail = "已适度校正曝光，保留商品本身的颜色与细节。"
    else:
        edges = np.asarray(sample.filter(ImageFilter.FIND_EDGES))
        h, w = arr.shape
        border = max(2, min(h, w) // 6)
        outside = np.concatenate(
            [
                edges[1:border].ravel(),
                edges[-border:-1].ravel(),
                edges[1:-1, 1:border].ravel(),
                edges[1:-1, -border:-1].ravel(),
            ]
        )
        tool = Path(os.getenv("TRUPIC_CUTOUT", ROOT / ".trupic/bin/cutout"))
        if outside.size and (outside > 26).mean() > 0.10 and tool.is_file():
            try:
                subprocess.run(
                    [str(tool), str(folder / file), str(folder / "subject.png")],
                    timeout=18,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                with Image.open(folder / "subject.png") as cut:
                    opacity = np.asarray(cut.convert("RGBA"))[:, :, 3]
                    if 0.05 < (opacity > 128).mean() < 0.9:
                        file = "subject.png"
                        action = "主体抠图"
                        detail = "已保留原图主体并分离背景，请在预览中核对包装与标识。"
            except (subprocess.SubprocessError, OSError):
                pass
    return dict(
        width=original_size[0],
        height=original_size[1],
        risk=risk,
        action=action,
        detail=detail,
        file=file,
    )


def picture(plan, asset_path, area, variant, scene, background, dark, accent):
    w, h = area
    if asset_path:
        with Image.open(asset_path) as opened:
            photo = opened.convert("RGBA")
            if "A" in photo.getbands() and photo.getextrema()[-1][0] < 240:
                # Rebuild only the stage. Product pixels and package lettering remain from the photograph.
                from PIL import ImageColor

                yy, xx = np.mgrid[0 : area[1], 0:w]
                light = (
                    0.98
                    - 0.15 * (xx / w)
                    + 0.11
                    * np.exp(-((xx / w - 0.2) ** 2 + (yy / area[1] - 0.3) ** 2) * 7)
                )
                shade = (
                    np.array(ImageColor.getrgb(accent))[None, None, :]
                    * light[:, :, None]
                )
                area_img = Image.fromarray(np.uint8(np.clip(shade, 0, 255)))
                if background:
                    with Image.open(background) as backdrop:
                        area_img = ImageOps.fit(
                            backdrop, area, Image.Resampling.LANCZOS
                        )
                shadow = Image.new("L", area, 0)
                ImageDraw.Draw(shadow).ellipse(
                    (w * 0.24, area[1] * 0.80, w * 0.86, area[1] * 0.98), fill=78
                )
                shadow = shadow.filter(ImageFilter.GaussianBlur(max(5, int(w * 0.023))))
                area_img.paste(ImageColor.getrgb(dark), (0, 0, w, area[1]), shadow)
                box = photo.getbbox()
                photo = photo.crop(box) if box else photo
                photo.thumbnail(
                    (int(w * 0.83), int(area[1] * 0.94)), Image.Resampling.LANCZOS
                )
                area_img.paste(
                    photo,
                    ((w - photo.width) // 2, (area[1] - photo.height) // 2),
                    photo,
                )
            else:
                area_img = Image.new("RGB", area, dark)
                fitted = ImageOps.contain(photo, area, Image.Resampling.LANCZOS)
                area_img.paste(
                    fitted,
                    ((w - fitted.width) // 2, (area[1] - fitted.height) // 2),
                    fitted,
                )
            return area_img
    elif background or plan.get("scenePhoto"):
        with Image.open(
            background or ROOT / "server" / "scenes" / (plan["scenePhoto"] + ".webp")
        ) as photograph:
            if scene == 1 or variant % 2:
                ow, oh = photograph.size
                photograph = photograph.crop(
                    (int(ow * 0.12), int(oh * 0.12), int(ow * 0.95), int(oh * 0.95))
                )
            fitted = ImageOps.fit(
                photograph,
                area,
                Image.Resampling.LANCZOS,
                centering=(0.51, 0.52),
            )
            return fitted
    # Abstract imagery makes no claim about a merchant's products.
    out = Image.new("RGB", area, dark)
    draw = ImageDraw.Draw(out)
    radius = int(min(w, h) * (0.28 if w > h else 0.32))
    for i in range(8):
        x = int(w * ((0.77 + 0.055 * i) if w > h else (0.14 + 0.13 * i)))
        y = int(h * 0.61)
        draw.arc(
            (x - radius, y - radius, x + radius, y + radius),
            198,
            494,
            fill=accent,
            width=max(2, w // 130),
        )
    return out


def soundtrack(path):
    rate = 22050
    t = np.arange(rate * 9) / rate
    signal = np.zeros_like(t)
    for i, note in enumerate([261.63, 329.63, 392, 523.25, 392, 329.63] * 3):
        elapsed = t - i * 0.5
        mask = (elapsed >= 0) & (elapsed < 0.46)
        s = elapsed[mask]
        signal[mask] += (
            0.12
            * np.sin(2 * np.pi * note * s)
            * np.exp(-s * 8)
            * np.minimum(s / 0.012, 1)
        )
    with wave.open(str(path), "wb") as f:
        f.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        f.writeframes((signal * 32767).astype("<i2").tobytes())


def render(
    folder,
    plan,
    copy,
    kind,
    asset_path,
    ratio,
    variant,
    background=None,
    custom_font=None,
):
    from .posters import poster
    from .motion import frame
    from .campaign import storyboard
    from .typography import Typesetter

    typesetter = Typesetter(custom_font)
    folder.mkdir(parents=True, exist_ok=True)
    output = plan.get("output") or output_spec(kind, ratio)
    dims = (output["width"], output["height"])
    dense = "满屏字" in plan["original"] and variant == 0
    img = poster(
        plan,
        copy,
        asset_path,
        dims,
        variant,
        dense=dense,
        background=background,
        typesetter=typesetter,
    )
    img.save(
        folder / "poster.png", compress_level=6, dpi=(output["dpi"], output["dpi"])
    )
    with (folder / "copy.txt").open("w", encoding="utf-8") as fp:
        fp.write("\n\n".join(copy[x] for x in ("title", "body", "cta") if copy[x]))
    if kind == "video":
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ValueError("短片导出需要 FFmpeg，请在服务端安装后重试。")
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            tmp = Path(tmp)
            size = dims
            shots = copy.get("storyboard") or storyboard(plan, copy)
            for i, shot in enumerate(shots):
                frame(
                    plan, shot, i, asset_path, size, variant, background, typesetter
                ).save(tmp / f"shot{i}.png")
            pace = plan.get("promptBrief", {}).get("reading", {}).get("pace", "steady")
            movement = {"quiet": 0.00015, "steady": 0.0004, "brisk": 0.0009}[pace]
            soundtrack(tmp / "track.wav")
            subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-framerate",
                    "1/3",
                    "-i",
                    str(tmp / "shot%d.png"),
                    "-i",
                    str(tmp / "track.wav"),
                    "-vf",
                    f"zoompan=z='1+{movement}*mod(on,72)':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=72:s={size[0]}x{size[1]}:fps=24,setsar=1,format=yuv420p",
                    "-c:v",
                    "libx264",
                    "-threads",
                    "2",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-c:a",
                    "aac",
                    "-t",
                    "9",
                    "-movflags",
                    "+faststart",
                    str(folder / "video.mp4"),
                ],
                timeout=300,
                check=True,
                capture_output=True,
            )
    return dict(
        fonts=sorted(typesetter.used),
        fallback=typesetter.fallback_used,
        poster="poster.png",
        download={"poster": "poster.png", "video": "video.mp4", "copy": "copy.txt"}[
            kind
        ],
    )
