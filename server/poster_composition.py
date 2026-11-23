"""Picture placement and text areas for the reference-led poster layouts."""

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageStat

from .posters import extend_edges

# Picture, brand, headline, offer/conditions and action, in that order.
LAYOUTS = {
    "food-motion": {
        "portrait": (
            (0.055, 0.265, 0.96, 0.79),
            (0.065, 0.045, 0.935, 0.085),
            (0.06, 0.09, 0.94, 0.25),
            (0.065, 0.82, 0.935, 0.907),
            (0.065, 0.918, 0.935, 0.978),
        ),
        "wide": (
            (0.43, 0.08, 0.972, 0.93),
            (0.05, 0.085, 0.40, 0.145),
            (0.045, 0.17, 0.41, 0.60),
            (0.05, 0.66, 0.40, 0.80),
            (0.05, 0.83, 0.40, 0.94),
        ),
        "role": "display",
        "points": 166,
    },
    "quiet-light": {
        "portrait": (
            (0.22, 0.38, 0.93, 0.78),
            (0.078, 0.06, 0.91, 0.106),
            (0.075, 0.135, 0.84, 0.34),
            (0.078, 0.82, 0.92, 0.897),
            (0.078, 0.91, 0.92, 0.97),
        ),
        "wide": (
            (0.51, 0.17, 0.93, 0.84),
            (0.07, 0.12, 0.45, 0.174),
            (0.067, 0.22, 0.465, 0.60),
            (0.07, 0.68, 0.45, 0.795),
            (0.07, 0.815, 0.45, 0.917),
        ),
        "role": "serif",
        "points": 128,
    },
    "photo-grid": {
        "portrait": (
            (0.07, 0.29, 0.93, 0.785),
            (0.07, 0.048, 0.93, 0.09),
            (0.067, 0.105, 0.933, 0.27),
            (0.07, 0.82, 0.93, 0.91),
            (0.07, 0.92, 0.93, 0.97),
        ),
        "wide": (
            (0.45, 0.095, 0.939, 0.895),
            (0.06, 0.095, 0.40, 0.153),
            (0.057, 0.19, 0.409, 0.59),
            (0.06, 0.66, 0.40, 0.79),
            (0.06, 0.815, 0.40, 0.915),
        ),
        "role": "display",
        "points": 145,
    },
}


def pixel_box(area, size):
    return tuple(round(value * size[i % 2]) for i, value in enumerate(area))


def boxes(treatment, size):
    return LAYOUTS[treatment]["wide" if size[0] > size[1] else "portrait"]


def mean_color(photo):
    if photo is None:
        return np.array((160, 115, 76))
    sample = photo.copy()
    sample.thumbnail((96, 96))
    mask = sample.getchannel("A") if sample.mode == "RGBA" else None
    return np.array(ImageStat.Stat(sample.convert("RGB"), mask).mean)


def stage(treatment, size, pigment, lighting):
    if treatment == "photo-grid":
        paper = np.array((245, 241, 228)) * 0.93 + pigment * 0.07
        return Image.new("RGB", size, tuple(np.uint8(paper)))
    x, y = np.meshgrid(np.linspace(0, 1, 192), np.linspace(0, 1, 192))
    if treatment == "quiet-light":
        base = np.array((25, 21, 22)) + pigment * 0.10
        beam = np.exp(-(((x - 0.72) / 0.35) ** 2) - ((y - 0.59) / 0.31) ** 2)
        glow = np.array((82, 66, 47)) + pigment * 0.10
    elif lighting == "dark":
        base = np.array((12, 22, 19)) + pigment * 0.10
        beam = np.exp(-(((x - 0.67) / 0.43) ** 2) - ((y - 0.52) / 0.39) ** 2)
        glow = np.array((97, 68, 48)) + pigment * 0.12
    else:
        base = np.array((235, 218, 151)) * 0.84 + pigment * 0.16
        # One diagonal light boundary gives the food a direction on an otherwise empty set.
        beam = np.clip((x + y * 0.48 - 0.28) * 1.25, 0, 1)
        glow = np.array((20, 23, 39))
    rgb = np.uint8(np.clip(base + beam[:, :, None] * glow, 0, 255))
    return Image.fromarray(rgb).resize(size, Image.Resampling.BILINEAR)


def edge_light(photo, size, bounds, flat):
    """Diffuse the photo edges into the text area, keeping the source on its own layer."""
    proxy = (240, max(1, round(240 * size[1] / size[0])))
    l0, t0, r0, b0 = (
        round(v * proxy[i % 2] / size[i % 2])
        for i, v in enumerate(bounds)
    )
    r0, b0 = max(l0 + 1, r0), max(t0 + 1, b0)
    glow = extend_edges(photo.convert("RGB"), proxy, (l0, t0, r0, b0))
    wide = size[0] > size[1]
    edge = glow.crop((r0 - 1, t0, r0, b0) if wide else (l0, b0 - 1, r0, b0))
    tone = tuple(ImageStat.Stat(edge).median)
    if flat:
        return Image.new("RGB", size, tone)
    yy, xx = np.ogrid[:proxy[1], :proxy[0]]
    dx = np.maximum(0, np.maximum(l0 - xx, xx - r0 + 1))
    dy = np.maximum(0, np.maximum(t0 - yy, yy - b0 + 1))
    distance = np.hypot(dx, dy) / min(proxy)
    mask = Image.fromarray(np.uint8(255 * np.clip(distance / 0.08, 0, 1)))
    glow.paste(glow.filter(ImageFilter.GaussianBlur(8)), mask=mask)
    mask = Image.fromarray(np.uint8(255 * np.clip(distance / 0.23, 0, 1)))
    glow.paste(tone, (0, 0, *proxy), mask)
    plate = glow.resize(size, Image.Resampling.BILINEAR)
    left, top, right, bottom = bounds
    ImageDraw.Draw(plate).rectangle((left, top, right - 1, bottom - 1), fill=tone)
    return plate


def picture_layout(treatment, size, photo, lighting, layers, photo_area=None, repair=False, *, framed=None, background=None, reference_color=None, plate=None):
    """Fit source pixels within a reserved picture zone and keep text areas clear."""
    pigment = mean_color(photo)
    custom_plate = plate is not None
    if plate is None:
        plate = stage(treatment, size, pigment, lighting)
    if background:
        with Image.open(background) as source:
            plate = Image.blend(ImageOps.fit(source.convert("RGB"), size), plate, 0.72)
    if reference_color:
        plate = Image.blend(plate, Image.new("RGB", size, tuple(reference_color)), 0.5)
    if framed is None:
        framed = treatment == "photo-grid" and photo_area is None
    if photo is None:
        if layers is not None:
            layers.append(("stage", plate.copy(), (0, 0)))
        return plate, None

    area = photo_area or pixel_box(boxes(treatment, size)[0], size)
    a, b, c, d = area
    alpha = photo.getchannel("A") if photo.mode == "RGBA" else None
    bounds = alpha.getbbox() if alpha is not None else None
    l, t, r, bottom = bounds or (0, 0, *photo.size)
    scale = min((c - a) / (r - l), (d - b) / (bottom - t))
    pw, ph = max(1, round(photo.width * scale)), max(1, round(photo.height * scale))
    x = round((a + c) / 2 - (l + r) * pw / (2 * photo.width))
    if framed:
        x = round(a - l * pw / photo.width)
    y = round((b + d) / 2 - (t + bottom) * ph / (2 * photo.height))
    visible = (
        x + l * pw / photo.width,
        y + t * ph / photo.height,
        x + r * pw / photo.width,
        y + bottom * ph / photo.height,
    )
    left, top, right, ground = visible

    def add_layer(name, image, position=(0, 0)):
        if layers is not None:
            layers.append((name, image, position))
        plate.paste(
            image, position, image.getchannel("A") if image.mode == "RGBA" else None
        )

    px, py, pr, pb = map(round, visible)
    if photo_area and not framed and not background and not reference_color and not custom_plate and (not alpha or alpha.getextrema() == (255, 255)):
        plate = edge_light(photo, size, (px, py, max(px + 1, pr), max(py + 1, pb)), repair)
    if layers is not None:
        layers.append(("stage", plate.copy(), (0, 0)))

    unit = min(size)
    if framed:
        rules = Image.new("RGBA", size)
        draw = ImageDraw.Draw(rules)
        gap = unit * 0.012
        edge = (left - gap, top - gap, right + gap, ground + gap)
        ink = tuple(np.uint8(np.clip(pigment * 0.35 + (20, 28, 34), 0, 132)))
        draw.rectangle(edge, outline=ink, width=max(1, round(unit * 0.002)))
        footer = (edge[0], edge[3], min(c + gap, edge[2] + unit * 0.06), edge[3])
        draw.line(footer, fill=ink, width=max(2, round(unit * 0.004)))
        add_layer("picture-frame", rules)
    elif bounds and not photo_area:
        shadow = Image.new("L", size)
        ImageDraw.Draw(shadow).ellipse(
            (left, ground - unit * 0.014, right, ground + unit * 0.032), fill=122
        )
        shade = Image.new("RGBA", size, (10, 9, 7))
        shade.putalpha(shadow.filter(ImageFilter.GaussianBlur(unit * 0.015)))
        add_layer("contact-shadow", shade)
    fitted = photo.crop((l, t, r, bottom)).resize(
        (max(1, pr - px), max(1, pb - py)), Image.Resampling.LANCZOS
    )
    add_layer("source-photo", fitted, (px, py))
    return plate, (x, y, x + pw, y + ph)
