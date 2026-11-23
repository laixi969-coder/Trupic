"""Editorial product and appointment layouts for an intact photographic silhouette."""

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageStat

from .poster_composition import picture_layout
from .shot_detail import textured_patch


PLATES = Path(__file__).with_name("scenes") / "moments"
SET_BRIEFS = {
    "columns": "奶油白纸张棚拍，上方四成空白。下方是向右延伸的透视表格地面，最右一列荧光黄，薄灰细线。预留前景商品和列名位置。",
    "reply": "薄荷色日光摄影棚，水波折射在墙上形成宽阔的浅色对话气泡，上方三分之一供排字。气泡尖角朝下方中央。下半部为清透的空地面，侧边有水光。",
}


def conversation(copy, asset, size, ts, layers, background, repair):
    """Composite today's photograph and measured type on the commercial set."""
    w, h = size
    def box(l, t, r, b):
        return (round(l * w), round(t * h), round(r * w), round(b * h))

    motif = copy["motif"]
    with Image.open(background or PLATES / (motif + ".webp")) as im:
        plate = im.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    with Image.open(asset) as im:
        photo = im.convert("RGBA")
    overlay = Image.new("RGBA", size)
    pen = ImageDraw.Draw(overlay)
    if motif == "columns":
        ink = "#141612"
        title = copy["title"].replace("一列", "\n一列", 1)
        ts.draw(pen, title, box(0.053, 0.015, 0.94, 0.313), w * 0.23, "display", ink)
        if copy.get("posterDeck"):
            ts.draw(pen, copy["posterDeck"], box(0.057, 0.318, 0.95, 0.379), w * 0.042, "body", ink)
        for label, x, y in (("AX", 0.075, 0.461), ("AY", 0.52, 0.432), ("AZ", 0.85, 0.402)):
            ts.draw(pen, label, box(x, y, x + 0.11, y + 0.04), w * 0.043, "numeric", ink)
        area = box(0.065, 0.517 if repair else 0.51, 0.97, 0.972)
    else:
        ink = "#063e3b"
        title = copy["title"].replace("「", "\n「", 1)
        ts.draw(pen, title, box(0.085, 0.069, 0.915, 0.297), w * 0.16, "display", ink, align="center")
        area = box(0.11, 0.401 if repair else 0.384, 0.89, 0.972)

    alpha = photo.getchannel("A")
    left, top, right, bottom = alpha.getbbox()
    a, b, c, d = area
    scale = min((c-a)/(right-left), (d-b)/(bottom-top))
    pw, ph = round((right-left)*scale), round((bottom-top)*scale)
    x, y = (a+c-pw)//2, (b+d-ph)//2
    # Use the uploaded silhouette to shape the contact shadow on the set.
    shade = Image.new("L", size)
    if motif == "columns":
        shadow = alpha.crop((left, top, right, bottom)).resize((pw, ph))
        shade.paste(shadow, (x + round(w * 0.012), y + round(w * 0.019)))
    else:
        ImageDraw.Draw(shade).ellipse((x+pw*0.14, y+ph*0.951, x+pw*1.20, y+ph*1.003), fill=215)
    shade = shade.filter(ImageFilter.GaussianBlur(w*0.014)).point(lambda n: round(n*0.38))
    plate.paste((36, 42, 36), (0, 0, w, h), shade)
    scene, product_box = picture_layout("photo-grid", size, photo, "", layers, area, framed=False, plate=plate)
    return scene, overlay, product_box


def compose(plan, copy, asset, size, background, ts, layers):
    w, h = size
    def box(left, top, right, bottom):
        return (round(left * w), round(top * h), round(right * w), round(bottom * h))

    with Image.open(asset) as im:
        photo = im.convert("RGBA")
    alpha = photo.getchannel("A")
    bounds = alpha.getbbox()
    mode = plan["design"]["photoLayout"]
    clock_object = mode == "clock-object"
    appointment = mode in ("time", "clock-object")
    tall = h / w >= 1.6
    pigment = ImageStat.Stat(photo.convert("RGB"), alpha).median
    dark = tuple(round(12 + channel * 0.24) for channel in pigment)
    light = (251, 239, 211)
    if appointment:
        paper = light
        shade = tuple(round(v * 0.80 + p * 0.20) for v, p in zip(light, pigment))
        ink = "#%02x%02x%02x" % dark
    else:
        paper = dark
        shade = tuple(round(23 + channel * 0.46) for channel in pigment)
        ink = "#fff2ce"
    if background and not appointment:
        # Keep the commissioned scene's lighting and colours in the actual export.
        with Image.open(background) as im:
            plate = ImageOps.fit(im.convert("RGB"), size, Image.Resampling.LANCZOS)
        header = plate.crop(box(0.035, 0.015, 0.97, 0.33)).convert("L")
        ink = "#12211e" if ImageStat.Stat(header).median[0] > 145 else "#fff5de"
    else:
        if background:
            with Image.open(background) as im:
                texture = ImageOps.fit(im.convert("L"), size)
        else:
            detail = textured_patch(photo, bounds)
            texture = ImageOps.fit(photo.crop(detail or bounds).convert("L"), size, Image.Resampling.BICUBIC)
        plate = ImageOps.colorize(texture, black=shade, white=paper)
    photo_area = box(0.40, 0.395, 0.99, 0.97) if appointment else box(0.21, 0.34, 0.98, 0.98)
    if clock_object:
        row = 0.61 if tall else 0.36
        # The saucer shares the numeral baseline. Its size is set in units of width,
        # so it stays circular on both a 3:4 card and a full-height 9:16 story.
        half = 0.213 * w / h
        photo_area = box(0.556, row - half, 0.988, row + half)
    scene, product_box = picture_layout("photo-grid", size, photo, "", layers,
                                       photo_area, framed=False, plate=plate)
    overlay = Image.new("RGBA", size)
    pen = ImageDraw.Draw(overlay)
    u = min(w, h)
    brand = plan.get("brandKit", {}).get("name") or plan["profile"].get("name", "")
    subject = plan.get("subject", "")
    label = "  ·  ".join(dict.fromkeys(v for v in (brand, subject) if v and v != "门店"))
    ts.draw(pen, label, box(0.052, 0.025, 0.95, 0.082), u * 0.031, "body", ink)
    title = copy["title"]
    # Keep the spoken pause when the headline turns the corner alongside the product.
    title = re.sub(r"([，。？！])(?=.)", r"\1\n", title, count=1)
    if clock_object:
        clock = plan["moment"]["clock"]
        ts.draw(pen, clock, box(0.73, 0.025, 0.949, 0.080), u * 0.048, "numeric", ink, align="right")
        ts.draw(pen, clock[:-1], box(0.035, row - half, 0.551, row + half),
                u * 0.58, "numeric", ink)
        title_area = box(0.045, 0.119, 0.955, 0.385) if tall else box(0.047, 0.575, 0.96, 0.855)
        ts.draw(pen, title, title_area, u * 0.126, "serif", ink, vertical="top")
        detail = plan["moment"]["note"]
        ts.draw(pen, detail, box(0.052, 0.865, 0.95, 0.965), u * 0.037, "body", ink)
    elif appointment:
        ts.draw(pen, plan["moment"]["clock"], box(0.043, 0.084, 0.97, 0.385),
                u * 0.47, "numeric", ink, vertical="bottom")
        ts.draw(pen, title, box(0.052, 0.44, 0.393, 0.91), u * 0.083, "serif", ink)
    else:
        ts.draw(pen, title, box(0.047, 0.095, 0.95, 0.33), u * 0.115, "serif", ink, vertical="top")
    return scene, overlay, product_box
