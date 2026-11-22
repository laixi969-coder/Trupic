"""Local creative layouts with source-pixel geometry retained for export checks."""

import re

from PIL import Image, ImageDraw, ImageFilter


def render_product(plan, cp, asset, dims, ts):
    role = plan["bundleRole"]
    w, h = dims
    unit = min(dims)
    kit = plan.get("brandKit", {})
    color = kit.get("color", "#315744")
    ink, paper = "#202c25", "#f4f1e9"
    image = Image.new("RGB", dims, paper)
    with Image.open(asset) as source:
        photo = source.convert("RGBA")
    draw = ImageDraw.Draw(image)

    def rect(box, fill, radius=0):
        box = tuple(round(v * dims[i % 2]) for i, v in enumerate(box))
        if radius:
            draw.rounded_rectangle(box, radius=round(radius * unit), fill=fill)
        else:
            draw.rectangle(box, fill=fill)

    def text(value, box, size=0.04, fill=ink, face="sans", align="left"):
        ts.draw(
            draw,
            value,
            tuple(v * dims[i % 2] for i, v in enumerate(box)),
            unit * size,
            face,
            fill,
            align,
        )

    def place(source, box, shadow=False):
        # Fit the visible alpha bounds, not the transparent margins. Return the
        # transform of the entire original canvas so pixel auditing stays exact.
        alpha = source.getchannel("A")
        bounds = alpha.getbbox() or (0, 0, *source.size)
        l, t, r, b = bounds
        x0, y0, x1, y1 = (v * dims[i % 2] for i, v in enumerate(box))
        scale = min((x1 - x0) / (r - l), (y1 - y0) / (b - t))
        visible = source.crop(bounds)
        vw, vh = (
            max(1, round(visible.width * scale)),
            max(1, round(visible.height * scale)),
        )
        visible = visible.resize((vw, vh), Image.Resampling.LANCZOS)
        x, y = round((x0 + x1 - vw) / 2), round((y0 + y1 - vh) / 2)
        if shadow and alpha.getextrema()[0] < 240:
            shade = Image.new("RGBA", dims)
            ImageDraw.Draw(shade).ellipse(
                (
                    x - vw * 0.06,
                    y + vh - vh * 0.025,
                    x + vw * 1.06,
                    y + vh + vh * 0.035,
                ),
                fill=(18, 36, 24, 45),
            )
            shade = shade.filter(ImageFilter.GaussianBlur(unit * 0.014))
            image.paste(shade, (0, 0), shade)
        image.paste(visible, (x, y), visible)
        sx, sy = vw / (r - l), vh / (b - t)
        return (
            x - l * sx,
            y - t * sy,
            x + (source.width - l) * sx,
            y + (source.height - t) * sy,
        )

    def brand():
        logo_id = kit.get("logo")
        if logo_id:
            folder = asset.parent.parent / logo_id
            path = folder / "subject.png"
            if not path.is_file():
                path = folder / "original.png"
            if path.is_file():
                with Image.open(path) as logo:
                    place(logo.convert("RGBA"), (0.81, 0.035, 0.94, 0.105))
        text(
            kit.get("name") or plan.get("profile", {}).get("name") or "",
            (0.06, 0.035, 0.72, 0.09),
            0.025,
            color,
        )

    def facts(box, size=0.037):
        text(cp["body"], box, size)

    if role == "overlay":
        image = Image.new("RGBA", dims)
        draw = ImageDraw.Draw(image)
        rect((0.04, 0.72, 0.96, 0.96), color, 0.025)
        rgb = tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))
        light = sum(v for v in rgb) / 3 > 150
        text(cp["title"], (0.08, 0.74, 0.92, 0.81), 0.060, ink if light else "white")
        text(cp["body"], (0.08, 0.82, 0.92, 0.94), 0.037, ink if light else "white")
        return image, None

    if role in ("white", "front", "side", "back"):
        image.paste("white", (0, 0, w, h))
        return image, place(photo, (0.12, 0.10, 0.88, 0.90))

    if role in ("scene", "livebackground"):
        # A local studio stage. No generated scenery or invented product pixels.
        for y in range(h):
            shade = y / h
            draw.line(
                (0, y, w, y),
                fill=tuple(
                    round(a + (b - a) * shade)
                    for a, b in zip((237, 240, 225), (193, 207, 175))
                ),
            )
        if role == "livebackground":
            rect((0, 0.78, 1, 1), "#dce3cc")
            box = place(photo, (0.64, 0.60, 0.93, 0.89), shadow=True)
            return image, box
        rect((0, 0.78, 1, 1), "#dce3cc")
        return image, place(photo, (0.16, 0.12, 0.84, 0.88), shadow=True)

    if role in ("box", "bag", "card"):
        if role == "card":
            rect((0.09, 0.30, 0.91, 0.74), "white", 0.015)
            rect((0.09, 0.72, 0.91, 0.74), color)
            box = place(photo, (0.28, 0.39, 0.72, 0.61))
        else:
            if role == "box":
                draw.polygon(
                    [
                        (w * 0.18, h * 0.30),
                        (w * 0.30, h * 0.20),
                        (w * 0.90, h * 0.20),
                        (w * 0.78, h * 0.30),
                    ],
                    fill="#ded9cc",
                )
                draw.polygon(
                    [
                        (w * 0.78, h * 0.30),
                        (w * 0.90, h * 0.20),
                        (w * 0.90, h * 0.74),
                        (w * 0.78, h * 0.84),
                    ],
                    fill="#c9c8b7",
                )
            else:
                draw.arc(
                    (w * 0.33, h * 0.13, w * 0.67, h * 0.43),
                    180,
                    360,
                    fill=color,
                    width=max(2, round(unit * 0.018)),
                )
            rect((0.18, 0.30, 0.78 if role == "box" else 0.82, 0.84), "#fffdf7")
            rect((0.18, 0.77, 0.78 if role == "box" else 0.82, 0.84), color)
            box = place(photo, (0.29, 0.43, 0.68, 0.63))
        return image, box

    if role == "guideline":
        text(cp["title"], (0.06, 0.04, 0.94, 0.14), 0.055, color, "serif")
        box = place(photo, (0.28, 0.20, 0.72, 0.41))
        rect((0.06, 0.49, 0.48, 0.65), color, 0.01)
        rect((0.51, 0.49, 0.94, 0.65), "#e3e6d9", 0.01)
        # The same brand data is visible, with swatches and a type specimen.
        text(cp["body"], (0.06, 0.69, 0.94, 0.88), 0.032)
        text(kit.get("name", "") + " / Aa 0123", (0.06, 0.90, 0.94, 0.96), 0.030)
        return image, box

    if role in ("brandcard", "brandbanner"):
        rect((0, 0.89, 1, 1), color)
        text(cp["title"], (0.06, 0.06, 0.94, 0.16), 0.045, color, "serif")
        box = place(photo, (0.24, 0.24, 0.76, 0.65))
        facts((0.08, 0.73, 0.92, 0.84), 0.027)
        return image, box

    brand()
    if w > h:
        # Banners have a separate horizontal composition and retain readable terms.
        text(cp["title"], (0.06, 0.16, 0.56, 0.40), 0.072, color, "serif")
        facts((0.06, 0.43, 0.54, 0.66), 0.036)
        text(cp.get("terms"), (0.06, 0.73, 0.55, 0.92), 0.027)
        return image, place(photo, (0.61, 0.17, 0.94, 0.90), shadow=True)

    if role in ("announcement", "livecover"):
        text(cp["title"], (0.06, 0.13, 0.94, 0.26), 0.075, color, "serif")
        facts((0.06, 0.29, 0.94, 0.44), 0.047)
        rect((0, 0.80, 1, 1), "#e0e5d2")
        return image, place(photo, (0.19, 0.48, 0.81, 0.91), shadow=True)

    if role in ("benefit", "detail"):
        text(cp["title"], (0.06, 0.13, 0.94, 0.27), 0.074, color, "serif")
        clauses = [c.strip() for c in re.split(r"[；;·\n]", cp["body"]) if c.strip()]
        # Keep all supplied facts; use separate rows only for explicit separators.
        if 1 < len(clauses) <= 4:
            for i, line in enumerate(clauses):
                top = 0.35 + i * 0.14
                rect((0.06, top, 0.11, top + 0.005), color)
                text(line, (0.06, top + 0.02, 0.43, top + 0.115), 0.037)
        else:
            facts((0.06, 0.35, 0.43, 0.83), 0.038)
        return image, place(photo, (0.48, 0.34, 0.94, 0.90), shadow=True)

    if role in ("campaign", "promotion", "price"):
        title = (
            cp["title"].replace(" · ", " ·\n", 1) if role == "campaign" else cp["title"]
        )
        text(
            title,
            (0.06, 0.13, 0.94, 0.32),
            0.12 if role == "price" else 0.075,
            color,
            "numeric" if role == "price" else "serif",
        )
        facts((0.06, 0.36, 0.44, 0.73), 0.038)
        box = place(photo, (0.50, 0.35, 0.94, 0.80), shadow=True)
        rect((0.06, 0.86, 0.94, 0.862), "#bfc9b3")
        text(cp.get("terms"), (0.06, 0.88, 0.94, 0.96), 0.028)
        return image, box

    # Main image / social cover / closing page: complete product and copy.
    text(cp["title"], (0.06, 0.13, 0.94, 0.29), 0.082, color, "serif")
    area = (0.17, 0.33, 0.83, 0.79)
    if role == "closing":
        area = (0.29, 0.37, 0.71, 0.73)
    box = place(photo, area, shadow=True)
    rect((0.06, 0.84, 0.94, 0.842), "#bfc9b3")
    facts((0.06, 0.86, 0.94, 0.96), 0.033)
    return image, box
