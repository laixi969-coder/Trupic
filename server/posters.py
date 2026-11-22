"""Typeset merchant copy directly over a full-bleed photographic or printed scene."""

import re
from pathlib import Path
import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageOps, ImageStat

from .design import DIRECTIONS, choose_style, direction
from .media import PALETTES, picture
from .typography import Typesetter
from .lettering import apply_lettering

SCENES = Path(__file__).with_name("scenes")
CAMPAIGN = {art["plate"] for art in DIRECTIONS.values() if art.get("plate")}


def extend_edges(photo, size, box):
    """Continue the edge light into the margin while keeping the whole original photograph."""
    x, y, r, b = box
    image = photo.resize((r - x, b - y), Image.Resampling.LANCZOS)
    w, h = size
    # Build the extension at low resolution. Only the original photo needs full detail.
    proxy = image.resize((96, 96), Image.Resampling.BILINEAR)
    px, py, pr, pb = (
        round(n * 224 / (w if i % 2 == 0 else h)) for i, n in enumerate(box)
    )
    patch = proxy.resize((max(1, pr - px), max(1, pb - py)))
    arr = np.pad(
        np.asarray(patch), ((py, 224 - pb), (px, 224 - pr), (0, 0)), mode="edge"
    )
    stage = (
        Image.fromarray(arr)
        .filter(ImageFilter.GaussianBlur(2))
        .resize(size, Image.Resampling.BILINEAR)
    )
    stage.paste(image, (x, y))
    return stage


def frame_campaign(photo, size, protected):
    """Crop around the protected product silhouette; extend light only where needed."""
    w, h = size
    a, b, c, d = protected
    scale = min(
        max(w / photo.width, h / photo.height),
        w * 0.98 / ((c - a) * photo.width),
        h * 0.68 / ((d - b) * photo.height),
    )
    sw, sh = round(photo.width * scale), round(photo.height * scale)

    def offset(canvas, source, start, end, low, high, center):
        preferred = (canvas - source) * center
        return round(
            max(
                low * canvas - start * source,
                min(preferred, high * canvas - end * source),
            )
        )

    x = offset(w, sw, a, c, 0.01, 0.99, 0.69)
    y = offset(h, sh, b, d, 0.245, 0.925, 0.61)
    box = max(0, x), max(0, y), min(w, x + sw), min(h, y + sh)
    src = tuple((v - (x if i % 2 == 0 else y)) / scale for i, v in enumerate(box))
    src = (
        max(0, src[0]),
        max(0, src[1]),
        min(photo.width, src[2]),
        min(photo.height, src[3]),
    )
    visible = photo.crop(src)
    if box == (0, 0, w, h):
        return visible.resize(size, Image.Resampling.LANCZOS)
    return extend_edges(visible, size, box)


def backdrop(
    plan, asset, size, style, variant, scene, background, art, graphic_type=None
):
    w, h = size
    name = plan.get("scenePhoto", "")
    if name == "matcha":
        name = "matcha-campaign"
    path = asset or background or (SCENES / (name + ".webp") if name else None)
    if not path:
        return picture(
            plan, None, size, variant, scene, None, art["ink"], art["accent"]
        )
    with Image.open(path) as source:
        cutout = asset and "A" in source.getbands() and source.getextrema()[-1][0] < 240
        if cutout:
            area = (round(w * 0.49), round(h * 0.82)) if w > h else (w, round(h * 0.51))
            photo = picture(
                plan, asset, area, variant, scene, background, art["ink"], art["accent"]
            )
        else:
            photo = ImageOps.exif_transpose(source).convert("RGB")
    if graphic_type and not asset and not background and name in CAMPAIGN:
        with Image.open(SCENES / "masks" / (name + ".png")) as silhouette:
            photo = apply_lettering(
                photo, plan, graphic_type, art, style, silhouette, bleed=w <= h
            )
    if cutout:
        x, y = (w - photo.width, round(h * 0.10)) if w > h else (0, round(h * 0.31))
        return extend_edges(photo, size, (x, y, x + photo.width, y + photo.height))
    # Campaign plates have a known title area. Wide crops preserve the whole subject
    # and extend the actual light into the opposite side of the frame.
    directed = not asset and (background or name in CAMPAIGN)
    if background and not asset:
        scale = min(w / photo.width, h / photo.height)
        pw, ph = round(photo.width * scale), round(photo.height * scale)
        x, y = w - pw, h - ph
        return extend_edges(photo, size, (x, y, w, h))
    if directed and w / h <= 1.10:
        protected = art.get("protected") if not background else None
        if protected:
            return frame_campaign(photo, size, protected)
        return ImageOps.fit(
            photo, size, Image.Resampling.LANCZOS, centering=(0.69, 0.61)
        )
    if directed:
        # Trim only the deliberately empty upper part of the portrait master.
        if photo.height > photo.width:
            photo = photo.crop(
                (0, round(photo.height * 0.22), photo.width, photo.height)
            )
        scale = min(w * 0.68 / photo.width, h / photo.height)
        pw, ph = round(photo.width * scale), round(photo.height * scale)
        x = w - pw
        y = h - ph
    else:
        # Merchant snapshots retain their complete framing and legible packaging.
        wide = w > h
        scale = min(
            w * (0.49 if wide else 1) / photo.width,
            h * (0.82 if wide else 0.51) / photo.height,
        )
        pw, ph = max(1, round(photo.width * scale)), max(1, round(photo.height * scale))
        x = w - pw if wide else (w - pw) // 2
        y = (h - ph) // 2 if wide else round(h * 0.31 + (h * 0.51 - ph) / 2)
    return extend_edges(photo, size, (x, y, x + pw, y + ph))


def screen_ink(image, art):
    """Small repeating threshold matrix simulates separate screen-print ink densities."""
    levels = np.asarray(ImageOps.grayscale(image), dtype=np.uint16) * 4
    matrix = (
        np.array(
            [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
            dtype=np.uint16,
        )
        * 16
    )
    dots = np.tile(matrix, (image.height // 4 + 1, image.width // 4 + 1))[
        : image.height, : image.width
    ]
    values = np.uint8(np.minimum(levels // 255 + (levels % 255 > dots), 4) * 63)
    return ImageOps.colorize(
        Image.fromarray(values), art["ink"], art["paper"], mid=art["accent"]
    )


def luminance(rgb):
    channels = [v / 255 for v in rgb]
    linear = [
        v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels
    ]
    return sum(c * k for c, k in zip(linear, (0.2126, 0.7152, 0.0722)))


def poster(
    plan,
    copy,
    asset_path,
    size,
    variant=0,
    scene=0,
    dense=False,
    background=None,
    typesetter=None,
):
    w, h = size
    wide = w > h
    unit = min(w, h) / 1080
    style = (plan.get("design") or choose_style(plan))["id"]
    key = plan.get("sector") or direction(plan["original"], plan["profile"])[0]
    art = DIRECTIONS.get(key, DIRECTIONS["general"])
    if key == "general" and plan["subject"] in PALETTES:
        dark, paper, accent = PALETTES[plan["subject"]]
        art = {**art, "ink": dark, "paper": paper, "accent": accent}
    if style == "screenprint":
        art = {**art, "ink": "#202a30", "accent": "#e98a57", "paper": "#ffedc0"}
    ts = typesetter or Typesetter()
    img = backdrop(plan, asset_path, size, style, variant, scene, background, art, ts)
    if asset_path or background or plan.get("scenePhoto") not in CAMPAIGN | {"matcha"}:
        img = apply_lettering(
            img,
            plan,
            ts,
            art,
            style,
            margin=bool(asset_path or background or plan.get("scenePhoto")),
        )
    if style == "screenprint" and not asset_path:
        img = screen_ink(img, art)
    paint = ImageDraw.Draw(img)
    brand = plan["profile"].get("name") or "响指出片 Trupic"
    subject = (
        plan.get("promptBrief", {}).get("reading", {}).get("product")
        or plan["profile"].get("product")
        or plan["subject"]
    )
    title = (copy["title"], plan["shot"], copy["cta"])[scene % 3]
    sentence_pair = re.fullmatch(r"(.{3,11}?[。？！])(.{3,11})", title)
    if not wide and sentence_pair:
        title = "\n".join(sentence_pair.groups())
    elif not wide and 6 <= len(title) <= 20 and len(title.split("，", 1)[0]) >= 3:
        if "，" in title:
            title = title.replace("，", "，\n", 1)
        else:
            title = re.sub(r"^(「[^」]{2,5}」)(?=.{4,}$)", r"\1\n", title)
    offer = copy.get("offer", "")
    lead = plan.get("facts") or plan["profile"].get("facts", "")
    if dense:
        lead = copy["body"]
    elif not lead and not offer:
        sentences = copy["body"].split("。")
        if (
            len(sentences) > 1
            and sentences[0].strip() in (subject, brand)
            and sentences[1].strip()
        ):
            sentences = sentences[1:]
        lead = sentences[0].strip() + "。"
    terms = copy.get("terms", "")
    if terms and terms not in lead:
        lead = "。".join(filter(None, (lead.rstrip("。"), terms.rstrip("。")))) + "。"
    if lead.strip("。") == offer:
        lead = ""
    cta = copy["cta"] if scene != 2 else brand

    def rect(box):
        return tuple(round(v * (w if i % 2 == 0 else h)) for i, v in enumerate(box))

    def foreground(box, accent=False):
        sample = img.crop(box).resize((20, 16))
        local = luminance(ImageStat.Stat(sample).median)
        candidates = (
            [art["accent"], art["paper"], art["ink"]]
            if accent
            else [art["paper"], art["ink"]]
        )
        scores = []
        for color in candidates:
            ink = luminance(ImageColor.getrgb(color))
            scores.append((max(local, ink) + 0.05) / (min(local, ink) + 0.05))
        return (
            candidates[0] if scores[0] >= 4.5 else candidates[scores.index(max(scores))]
        )

    def text(
        value, box, fs, role="body", align="left", vertical="middle", accent=False
    ):
        if asset_path and wide and box[1] >= 0.09:
            box = (box[0], box[1], min(box[2], 0.50), box[3])
        ts.draw(
            paint,
            value,
            rect(box),
            fs * unit,
            role,
            lambda bounds: foreground(bounds, accent),
            align,
            vertical,
        )

    text(brand, (0.05, 0.033, 0.64, 0.078), 35, "display")
    if subject != brand:
        text(subject, (0.68, 0.035, 0.95, 0.076), 22, align="right")
    if dense and not asset_path:
        # The merchant requested a text-led first version. Keep every transaction condition.
        paint.rectangle(rect((0.025, 0.092, 0.975, 0.977)), fill=art["paper"])
        text(title, (0.055, 0.11, 0.945, 0.41), 185, "display")
        body = lead if not offer or offer in lead else offer + "。" + lead
        text(body, (0.055, 0.43, 0.945, 0.81), 96)
        text(cta, (0.055, 0.83, 0.945, 0.95), 68, "display", accent=True)
        return img
    custom_photo = bool(asset_path) or (
        not background and plan.get("scenePhoto") not in CAMPAIGN | {"matcha"}
    )
    if custom_photo and not wide and offer:
        # All text above the complete source photograph. The footer carries conditions.
        headline_first = style != "swiss"
        upper, lower = (title, offer) if headline_first else (offer, title)
        text(
            upper,
            (0.05, 0.092, 0.94, 0.227),
            163,
            ("serif" if style == "editorial" else "display")
            if headline_first
            else "numeric",
            vertical="bottom",
        )
        text(
            lower,
            (0.052, 0.232, 0.94, 0.302),
            76,
            "numeric" if headline_first else "display",
            vertical="top",
        )
    elif style == "editorial":
        # Short Chinese titles form a vertical spine; Latin words keep their reading direction.
        vertical_title = (
            not wide
            and not custom_photo
            and key != "beauty"
            and bool(re.fullmatch(r"[\u3400-\u9fff]{2,6}", title))
        )
        if vertical_title:
            text(
                "\n".join(title),
                (0.054, 0.11, 0.255, 0.67),
                148,
                "serif",
                vertical="top",
            )
            text(offer, (0.30, 0.14, 0.93, 0.22), 61, "numeric")
        else:
            text(
                title,
                (0.05, 0.12, 0.60 if wide else 0.95, 0.58 if wide else 0.31),
                158,
                "serif",
                vertical="top",
            )
            text(
                offer,
                (
                    0.052,
                    0.615 if wide else 0.32,
                    0.49 if wide else 0.7,
                    0.72 if wide else 0.395,
                ),
                56,
                "numeric",
            )
    elif style == "swiss" and offer:
        single = re.fullmatch(
            r"([^，/／]+?)\s*[/／]\s*(杯|份|位|人|件|套|瓶|单)", offer
        )
        price, measure = single.groups() if single else (offer, "")
        text(
            price,
            (0.043, 0.112, 0.49 if wide else 0.84, 0.45 if wide else 0.287),
            235,
            "numeric",
            vertical="bottom",
            accent=True,
        )
        caption = " · ".join(filter(None, ("每" + measure if measure else "", terms)))
        text(
            caption,
            (
                0.05,
                0.455 if wide else 0.29,
                0.48 if wide else 0.82,
                0.53 if wide else 0.343,
            ),
            35,
        )
        if terms:
            lead = lead.replace(terms.rstrip("。"), "").strip(" ，。")
        text(
            title,
            (
                0.049,
                0.54 if wide else 0.355,
                0.51 if wide else (0.95 if custom_photo else 0.58),
                0.72 if wide else (0.45 if custom_photo else 0.485),
            ),
            88,
            "display",
            vertical="top",
        )
    elif style == "swiss":
        text(
            title,
            (0.047, 0.11, 0.54 if wide else 0.95, 0.59 if wide else 0.305),
            188,
            "display",
            vertical="top",
        )
    elif style == "screenprint":
        text(
            title,
            (0.043, 0.10, 0.57 if wide else 0.96, 0.56 if wide else 0.30),
            183,
            "display",
            vertical="bottom",
            accent=True,
        )
        text(
            offer,
            (
                0.048,
                0.60 if wide else 0.313,
                0.48 if wide else 0.73,
                0.74 if wide else 0.397,
            ),
            80,
            "numeric",
        )
    elif not wide and not custom_photo and key in {"auto", "clean", "commerce"}:
        if key == "commerce":
            if re.fullmatch(
                r"[\u3400-\u9fff]{4}|[\u3400-\u9fff]{6}|[\u3400-\u9fff]{8}", title
            ):
                split = len(title) // 2
                title = title[:split] + "\n" + title[split:]
            text(title, (0.047, 0.118, 0.60, 0.472), 164, "display", vertical="top")
            text(offer, (0.051, 0.49, 0.55, 0.59), 71, "numeric")
        elif key == "auto":
            text(
                title,
                (0.045, 0.145, 0.955, 0.349),
                227,
                "display",
                align="center",
                vertical="bottom",
            )
            text(offer, (0.055, 0.365, 0.94, 0.423), 64, "numeric", align="center")
        else:
            text(title, (0.11, 0.099, 0.89, 0.269), 174, "display", align="center")
            text(offer, (0.13, 0.279, 0.87, 0.355), 72, "numeric", align="center")
    else:
        text(
            title,
            (0.045, 0.106, 0.55 if wide else 0.95, 0.54 if wide else 0.293),
            164,
            art["type"],
            vertical="bottom",
        )
        text(
            offer,
            (
                0.05,
                0.57 if wide else 0.313,
                0.46 if wide else 0.73,
                0.72 if wide else 0.399,
            ),
            82,
            "numeric",
            accent=True,
        )
    # A stage and its photographic edge extension provide clean local areas for the supporting copy.
    text(
        lead,
        (
            0.052,
            0.766 if wide else 0.829,
            0.50 if wide else 0.76,
            0.856 if wide else 0.902,
        ),
        29,
        vertical="bottom",
    )
    text(
        cta,
        (0.052, 0.87 if wide else 0.916, 0.60 if wide else 0.76, 0.96),
        42,
        "display",
    )
    if not asset_path and (background or plan.get("scenePhoto")):
        text("创意场景示意", (0.758, 0.93, 0.953, 0.969), 18, "body", align="right")
    return img
