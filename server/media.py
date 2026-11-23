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


def photo_layout_features(path):
    """Summarize the pixels that will be placed, ignoring transparent margins."""
    with Image.open(path) as source:
        source.thumbnail((192, 192), Image.Resampling.BOX)
        preview = source.convert("RGBA")
    bounds = preview.getchannel("A").getbbox()
    if not bounds:
        return {}
    preview = preview.crop(bounds).resize((64, 64), Image.Resampling.BOX)
    opacity = np.asarray(preview.getchannel("A")) > 160
    if not opacity.any():
        return {}
    grey = np.asarray(preview.convert("L"), dtype=float)
    visible = grey[opacity]
    # Mask out the matte so its hidden RGB cannot create artificial texture.
    grey = np.where(opacity, grey, np.median(visible))
    tiles = grey.reshape(8, 8, 8, 8)
    local_variation = tiles.std(axis=(1, 3))
    dx = np.abs(np.diff(grey, axis=1, prepend=grey[:, :1]))
    dy = np.abs(np.diff(grey, axis=0, prepend=grey[:1]))
    low, high = np.percentile(visible, (10, 90))
    return {
        "aspect": round((bounds[2] - bounds[0]) / (bounds[3] - bounds[1]), 3),
        "calmArea": round(float((local_variation < 10).mean()), 3),
        "edgeDensity": round(float((np.maximum(dx, dy)[opacity] > 20).mean()), 3),
        "tonalRange": round(float(high - low), 1),
        "brightness": round(float(np.median(visible)), 1),
    }


def inspect_upload(source, folder):
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source) as raw:
            # Some phones store an auxiliary HDR image in the same JPEG (MPO).
            # The first frame is the owner's ordinary, full-colour photograph.
            if raw.format not in {"JPEG", "MPO", "PNG", "WEBP"}:
                raise ValueError("请选择 JPG、PNG 或 WebP 图片。")
            if raw.width * raw.height > 32_000_000:
                raise ValueError("图片超过 3200 万像素，请先缩小。")
            original_size = raw.size
            image = ImageOps.exif_transpose(raw).convert("RGBA")
            alpha = image.getchannel("A")
            supplied_subject = image if alpha.getextrema()[0] < 240 else None
            canvas = Image.new("RGB", image.size, "white")
            canvas.paste(image, mask=alpha)
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
    elif supplied_subject is not None and alpha.getbbox():
        supplied_subject.save(folder / "subject.png")
        file, action, detail = (
            "subject.png",
            "主体抠图",
            "已沿用上传文件的透明轮廓，请确认主体与标识。",
        )
    elif lum < 65 or lum > 212:
        fixed = ImageEnhance.Brightness(image).enhance(min(1.25, max(0.86, 130 / lum)))
        fixed.save(folder / "adjusted.png")
        file = "adjusted.png"
        action = "轻度调光"
        detail = "已适度校正曝光，保留商品本身的颜色与细节。"
    else:
        tool = Path(os.getenv("TRUPIC_CUTOUT", ROOT / ".trupic/bin/cutout"))
        if tool.is_file():
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
                        # Native segmentation supplies the matte. Keep source RGB verbatim.
                        with Image.open(folder / "original.png") as original:
                            subject = original.convert("RGBA")
                        subject.putalpha(cut.getchannel("A").resize(subject.size))
                        subject.save(folder / "subject.png")
                        file = "subject.png"
                        action = "主体抠图"
                        detail = "已保留原图主体并分离背景，请在预览中核对包装与标识。"
            except (subprocess.SubprocessError, OSError):
                pass
    return dict(
        width=original_size[0],
        height=original_size[1],
        risk=risk,
        suppliedTransparency=supplied_subject is not None,
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


def soundtrack(path, optical=False, duration=9, cuts=(0,3,6)):
    rate = 22050
    t = np.arange(rate * duration) / rate
    signal = np.zeros_like(t)
    for i, note in enumerate([261.63, 329.63, 392, 523.25, 392, 329.63] * ((duration + 2) // 3)):
        elapsed = t - i * 0.5
        mask = (elapsed >= 0) & (elapsed < 0.46)
        s = elapsed[mask]
        signal[mask] += (
            0.12
            * np.sin(2 * np.pi * note * s)
            * np.exp(-s * 8)
            * np.minimum(s / 0.012, 1)
        )
    if optical:
        # A low tonal bed and three shutter transients follow the cuts of the optics film.
        signal = 0.055 * np.sin(2 * np.pi * 55 * t) + 0.025 * np.sin(
            2 * np.pi * 82.41 * t
        )
        signal *= np.minimum(t / 0.22, 1) * np.clip((duration - t) / 0.45, 0, 1)
        rng = np.random.default_rng(40)
        for when in (cut + 0.05 for cut in cuts):
            span = (t >= when) & (t < when + 0.13)
            elapsed = t[span] - when
            signal[span] += 0.32 * rng.normal(size=span.sum()) * np.exp(-49 * elapsed)
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
    repair=False,
):
    from .posters import poster
    from .motion import frame
    from .campaign import storyboard
    from .typography import Typesetter

    from .visual_review import product_geometry, map_box
    from .campaign_frame import campaign_frame, film_planes, moving_frame, video_stage
    from .film_timing import camera_tick, frame_count
    from .film_edit import encode
    from .poster_composition import LAYOUTS

    typesetter = Typesetter(custom_font)
    folder.mkdir(parents=True, exist_ok=True)
    output = plan.get("output") or output_spec(kind, ratio)
    dims = (output["width"], output["height"])
    dense = kind == "poster" and "满屏字" in plan["original"] and variant == 0
    frames = []
    original_box = product_geometry(dims, asset_path) if asset_path else None

    directed = (kind == "video" and output.get("duration", 9) != 9) or repair or (kind == "video" and asset_path is not None) or bool(
        plan.get("posterArt") and not (dense and not asset_path)
        and (
            kind == "video"
            or plan.get("design", {}).get("id") in {"riso", "ipscene", *LAYOUTS}
            or (asset_path and plan.get("design", {}).get("id", "product") == "product")
        )
    )
    layers = {}
    shot_titles = {}
    video_renderer = None
    pace = plan.get("promptBrief", {}).get("reading", {}).get("pace", "steady")
    cloud_frames = Path(plan["videoBackground"]) if plan.get("videoBackground") else None
    if cloud_frames:
        background = cloud_frames / "001.jpg"
    silhouette = None
    if asset_path and asset_path.name == "subject.png":
        with Image.open(asset_path) as subject:
            alpha_box = subject.getchannel("A").getbbox()
            if alpha_box:
                silhouette = tuple(v / subject.size[i % 2] for i,v in enumerate(alpha_box))

    def draw_frame(index, shot=None, movement=0):
        typesetter.audit_text = [] if kind != "copy" else None
        box = original_box
        layer_info = {}
        directed_cover = plan.get("design", {}).get("id") in ("photo-grid", "quiet-light", "riso") and plan.get("bundleRole") in (
            "hero", "cover", "campaign", "promotion", "price", "banner"
        )
        if plan.get("bundleRole") and kind == "poster" and asset_path and not (plan.get("layoutOverride") or directed_cover):
            from .product_bundle import render_product
            image, box = render_product(plan, copy, asset_path, dims, typesetter, background)
        elif directed:
            save_design = kind == "poster" and index == 0
            separate_shot = shot and asset_path and (asset_path.name == "subject.png" or cloud_frames) and (cloud_frames or not plan.get("posterArt", {}).get("print"))
            source_layers = [] if save_design or separate_shot else None
            typesetter.editable_text = [] if save_design or shot else None
            plate, overlay, box = campaign_frame(
                plan,
                copy,
                shot,
                dims,
                asset_path,
                background,
                typesetter,
                index,
                source_layers,
                repair=repair,
            )
            if save_design:
                from .design_source import save_source

                save_source(
                    folder / "poster.svg", dims, source_layers, typesetter.editable_text
                )
            image = plate.copy()
            image.paste(overlay, mask=overlay.getchannel("A"))
            if shot:
                shot_titles[index] = typesetter.editable_text
                planes = film_planes(source_layers, dims)
                plate, foreground = planes or (plate, None)
                layers[index] = plate, foreground, overlay
                layer_info = {
                    "cameraShot": index,
                    "evidence": shot.get("evidence"),
                    "pace": pace,
                    "plate": plate.resize((160, 160)),
                    "overlay": overlay.resize((160, 160)),
                    "foreground": foreground.resize((160, 160)) if foreground else None,
                }

        elif shot is not None:
            image = frame(
                plan, shot, index - 1, asset_path, dims, variant, background, typesetter
            )
            if box:
                box = map_box(box, typesetter.camera, dims)
        else:
            image = poster(
                plan,
                copy,
                asset_path,
                dims,
                variant,
                dense=dense,
                background=background,
                typesetter=typesetter,
            )
        if kind != "copy":
            frames.append(
                {
                    "text": typesetter.audit_text,
                    "size": dims,
                    "product": box,
                    "subjectBounds": tuple(
                        box[i % 2] + v * (box[i % 2 + 2] - box[i % 2])
                        for i, v in enumerate(silhouette)
                    ) if silhouette and box else box,
                    "preview": image.convert("RGB").resize((160, 160)),
                    "movement": movement,
                    **layer_info,
                }
            )
        return image

    img = draw_frame(0)
    img.save(
        folder / "poster.png", compress_level=6, dpi=(output["dpi"], output["dpi"])
    )
    with (folder / "copy.txt").open("w", encoding="utf-8") as fp:
        fields = ("body", "cta") if "moment" in plan else ("title", "body", "cta")
        lines = [copy[x] for x in fields if copy[x]]
        if copy.get("writingSkill", {}).get("posterHeadings") and "moment" not in plan:
            for detail in (copy.get("offer"), copy.get("terms")):
                if detail and not any(detail in line for line in lines):
                    lines.append(detail)
        fp.write("\n\n".join(lines))
    if kind == "video":
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ValueError("短片导出需要 FFmpeg，请在服务端安装后重试。")
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            tmp = Path(tmp)
            size = dims
            shots = copy.get("storyboard") or storyboard(plan, copy, asset_path)
            drift = {"quiet": 0.0006, "steady": 0.0009, "brisk": 0.0012}[pace]
            for i, shot in enumerate(shots):
                movement = drift * (1.6 if i == 0 else 1.2 if i == 1 else 0.65) if directed else drift
                image = draw_frame(i + 1, shot, movement)
                frames[-1].update(startFrame=shot["start"]*24, frameCount=frame_count(shot))
                if not directed:
                    image.save(tmp / f"shot{i}.png")
            soundtrack(
                tmp / "track.wav", optical=bool(plan.get("posterArt", {}).get("optics")),
                duration=shots[-1]["end"], cuts=[s["start"] for s in shots]
            )
            if directed:
                def motion(bg, fg, index, tick):
                    if cloud_frames:
                        with Image.open(cloud_frames / f"{shots[index-1]['start']*24+tick+1:03d}.jpg") as cloud:
                            bg = video_stage(cloud)
                    return moving_frame(bg, fg, index, camera_tick(tick, frame_count(shots[index-1])), pace=pace)
                if cloud_frames:
                    for index, (bg, fg, overlay) in layers.items():
                        sequence = []
                        for tick in range(frame_count(shots[index-1])):
                            expected = motion(bg, fg, index, tick)
                            expected.paste(overlay, mask=overlay.getchannel("A"))
                            sequence.append(expected.resize((80,80)))
                        frames[index]["sequence"] = sequence
                video_renderer = encode(
                    layers, folder, tmp / "track.wav", dims, shots,
                    motion, shot_titles, pace, dynamic=bool(cloud_frames),
                )
            else:
                video_renderer = "FFmpeg"
                camera = f"zoompan=z='1+{drift}*mod(on,72)':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=72:s={size[0]}x{size[1]}:fps=24"
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
                        camera + ",setsar=1,format=yuv420p",
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
        frames=frames,
        videoRenderer=video_renderer,
        fonts=sorted(typesetter.used),
        fallback=typesetter.fallback_used,
        poster="poster.png",
        download={"poster": "poster.png", "video": "video.mp4", "copy": "copy.txt"}[
            kind
        ],
    )
