"""Use real Chinese and Latin glyphs as compositional shapes behind product silhouettes."""

from PIL import Image, ImageDraw, ImageChops, ImageOps, ImageStat
import re

from .campaign import copy_route

OPTIONS = {"auto", "both", "han", "latin", "off"}
# One dominant letterform and its optical center in each full-bleed original plate.
PLACEMENTS = {
    "auto": ("latin", 0.49, 0.631, 1.02),
    "tea": ("latin", 0.50, 0.566, 1.07),
    "commerce": ("han", 0.71, 0.51, 0.64),
    "home": ("han", 0.71, 0.59, 0.53),
    "clean": ("latin", 0.51, 0.535, 1.03),
    "retail": ("han", 0.74, 0.489, 0.60),
    "beauty": ("latin", 0.525, 0.566, 1.00),
}


def glyphs(word, width, ts, role, outlined):
    size = 240
    runs = list(ts.runs(word, size, role))
    if not runs:
        return None
    pen = 10
    mask = Image.new("L", (int(ts.width(word, size, role)) + 28, 410))
    d = ImageDraw.Draw(mask)
    for path, font, run in runs:
        d.text(
            (pen, 282),
            run,
            font=font,
            anchor="ls",
            fill=0 if outlined else 255,
            stroke_width=2 if outlined else 0,
            stroke_fill=255,
        )
        pen += font.getlength(run)
        ts.used.add(" ".join(font.getname()))
        if ts.custom and path != ts.custom:
            ts.fallback_used = True
    box = mask.getbbox()
    if not box:
        return None
    mask = mask.crop(box)
    return mask.resize(
        (width, max(1, round(width * mask.height / mask.width))),
        Image.Resampling.LANCZOS,
    )


def apply_lettering(
    image, plan, ts, art, style, subject=None, margin=False, bleed=True
):
    mode = plan.get("lettering", "auto")
    if mode == "off" or (mode == "auto" and plan.get("posterArt") and
                         plan["posterArt"].get("composition") not in ("ingredient", "projection") and
                         not plan["posterArt"].get("modelMark")):
        return image
    row = copy_route(plan) or {}
    product = plan["profile"].get("product") or plan["subject"]
    word = re.search(r"[A-Za-z][A-Za-z0-9-]{1,12}", product)
    char = re.search(r"[\u3400-\u9fff]", product)
    han = row.get("han") or (char.group() if char else "选")
    latin = row.get("latin") or (word.group().upper() if word else "EDIT")
    key = plan.get("sector", "general")
    default, cx, cy, span = PLACEMENTS.get(key, ("latin", 0.5, 0.54, 1.03))
    primary = default if mode in ("auto", "both") else mode
    if primary == "han" and default != "han":
        span = 0.57
    if primary == "latin" and default == "han":
        span = 1.02
    if not bleed:
        span = min(span, 0.9)
        cx = max(0.04 + span / 2, min(0.96 - span / 2, cx))
    w, h = image.size
    if margin:
        # Real product snapshots get a clear perimeter. No display lettering on their label.
        cx, cy, span = (0.27, 0.62, 0.43) if w > h else (0.50, 0.19, 0.77)
        if primary == "han":
            span *= 0.32
    overlay = Image.new("L", image.size)

    def place(lang, cx, cy, width, opacity, outline=False, rotate=False):
        word = han if lang == "han" else latin
        mark = glyphs(
            word,
            max(1, round(width * w)),
            ts,
            "serif"
            if lang == "han"
            and (key in ("tea", "home", "beauty") or style == "editorial")
            else "display",
            outline,
        )
        if mark is None:
            return
        if rotate:
            mark = mark.transpose(Image.Transpose.ROTATE_90)
        mark = mark.point(lambda v: round(v * opacity))
        x, y = round(cx * w - mark.width / 2), round(cy * h - mark.height / 2)
        overlay.paste(mark, (x, y))

    outline = style == "swiss" or key in ("tea", "commerce", "retail", "home")
    place(
        primary, cx, cy, span, 0.26 if margin else (0.78 if outline else 0.39), outline
    )
    if mode == "both" or (mode == "auto" and not margin):
        other = "han" if primary == "latin" else "latin"
        place(
            other,
            0.94 if not margin else 0.915,
            (0.815 if other == "han" else 0.275) if not margin else 0.18,
            0.048 if other == "han" else 0.13,
            0.72,
            False,
            other == "latin",
        )
    if subject is not None:
        overlay = ImageChops.subtract(overlay, subject.convert("L"))
        # The outermost sky pixels may be extended when reframing a tall master.
        ImageDraw.Draw(overlay).rectangle((0, 0, 1, h), fill=0)
        ImageDraw.Draw(overlay).rectangle((w - 2, 0, w, h), fill=0)
    if margin:
        protected = (
            (int(w * 0.50), int(h * 0.09), w, int(h * 0.92))
            if w > h
            else (0, int(h * 0.31), w, int(h * 0.82))
        )
        ImageDraw.Draw(overlay).rectangle(protected, fill=0)
    area = image.crop((int(w * 0.3), int(h * 0.38), int(w * 0.80), int(h * 0.72)))
    value = ImageStat.Stat(ImageOps.grayscale(area)).mean[0]
    color = art["paper"] if value < 135 else art["ink"]
    return Image.composite(Image.new("RGB", image.size, color), image, overlay)
