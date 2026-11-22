"""Render three camera setups with separate timed copy from the merchant's approved facts."""

import re
from PIL import Image, ImageDraw

from .design import DIRECTIONS
from .posters import backdrop


def frame(plan, shot, index, asset, size, variant, background, ts):
    w, h = size
    wide = w > h
    art = DIRECTIONS.get(plan.get("sector"), DIRECTIONS["general"])
    style = plan.get("design", {}).get("id", "product")
    im = backdrop(
        plan,
        asset,
        size,
        style,
        variant,
        index,
        background,
        art,
        ts if index == 2 else None,
    )
    # Start close to the object, move onto one detail, then reveal its complete silhouette.
    factor = (1.13, 2.25, 1)[index]
    if factor > 1:
        center_x = 0.73 if wide else 0.64
        center_y = 0.60
        if art.get("protected") and not asset and not wide:
            a, b, c, d = art["protected"]
            center_x = (a + c) / 2
            center_y = (b + d) / 2
        if index == 1 and not asset and plan.get("scenePhoto") and not background:
            # Centers refer to features on the original, directed campaign plates.
            portrait_details = {
                "auto": (0.43, 0.70),
                "tea": (0.71, 0.42),
                "commerce": (0.71, 0.71),
                "clean": (0.68, 0.49),
                "beauty": (0.73, 0.54),
                "home": (0.70, 0.64),
                "retail": (0.64, 0.62),
            }
            center_x, center_y = portrait_details.get(
                plan.get("sector"), (center_x, center_y)
            )
            if wide:
                center_x, center_y = (
                    (0.585, 0.67) if plan.get("sector") == "auto" else (0.78, 0.62)
                )
        cw, ch = round(w / factor), round(h / factor)
        left = min(w - cw, max(0, round(center_x * w - cw / 2)))
        top = min(h - ch, max(0, round(center_y * h - ch / 2)))
        im = im.crop((left, top, left + cw, top + ch)).resize(
            size, Image.Resampling.LANCZOS
        )
    # A continuous light falloff keeps captions legible while the original image fills the frame.
    horizontal = wide
    gradient = Image.new("L", (256, 1) if horizontal else (1, 256))
    gradient.putdata(
        [
            round((1 - i / 255) ** 1.6 * 197)
            if horizontal
            else round((i / 255) ** 2.4 * 220)
            for i in range(256)
        ]
    )
    im = Image.composite(
        Image.new("RGB", size, "#131516"),
        im,
        gradient.resize(size, Image.Resampling.BILINEAR),
    )
    d = ImageDraw.Draw(im)

    def text(value, box, scale, role="body", align="left"):
        if role in ("serif", "display") and len(value) > 7 and "，" in value:
            value = re.sub(r"(?<=，)(?=\S)", "\n", value, count=1)
        bounds = tuple(round(v * (w if i % 2 == 0 else h)) for i, v in enumerate(box))
        ts.draw(
            d, value, bounds, scale * min(w, h) / 1080, role, "#fff9ea", align, "middle"
        )

    brand = plan["profile"].get("name") or "响指出片 Trupic"
    text(
        brand,
        (
            0.05,
            0.78 if not wide else 0.25,
            0.82 if not wide else 0.46,
            0.823 if not wide else 0.33,
        ),
        31,
        "display",
    )
    if wide:
        text(
            shot["line"],
            (0.05, 0.34, 0.49, 0.66),
            103,
            "serif" if art["type"] == "serif" else "display",
        )
        text(shot["caption"], (0.052, 0.69, 0.49, 0.89), 39)
    else:
        text(
            shot["line"],
            (0.05, 0.825, 0.94, 0.927),
            93,
            "serif" if art["type"] == "serif" else "display",
        )
        text(shot["caption"], (0.052, 0.929, 0.943, 0.976), 30)
    if not asset and (background or plan.get("scenePhoto")):
        text(
            "创意场景示意",
            (0.74, 0.955 if wide else 0.025, 0.956, 0.989 if wide else 0.067),
            18,
            align="right",
        )
    return im
