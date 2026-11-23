"""Measure a photo-first poster in its output font before allocating the photograph."""

import re

from .visual_review import LayoutOverflow


def bleed_layout(size, ts, brand, copy, detail):
    w, h = size
    unit = min(size)
    margin = round(unit * 0.05)
    wide = w > h
    x = round(w * 0.54) if wide else margin
    width = w - margin - x
    title = copy["title"]
    offer, terms = copy.get("offer"), copy.get("terms")
    support = detail or re.split(r"[。！？]", copy.get("body", ""))[0]
    # Preserve the same factual support as the framed layout.
    if offer:
        support = terms
    elif terms and terms not in support:
        support = (support + "  " + terms).strip()
    title_ratio = 0.21 if wide else 0.144
    title_size = round(unit * (0.085 if offer else title_ratio))
    if ts.width(title.replace("\n", ""), title_size, "display") > width:
        title = re.sub(r"([，。！？：])(?=.)", r"\1\n", title, count=1)
    # The renderer keeps explicit lines and short headlines intact. Measure them
    # at their fitted width before reserving space for the photograph.
    if "\n" in title or len(title) <= 9:
        longest = max(ts.width(line, title_size, "display") for line in title.split("\n"))
        if longest > width - 3:
            title_size = max(7, int(title_size * (width - 4) / longest))
    # Each gap precedes its line. Price and conditions are read together.
    groups = [
        (brand, "body", 0.029, 0),
        (title, "display", title_size / unit, 0.021),
        (offer, "numeric", 0.18, 0.020),
        (support, "body", 0.036, 0.015),
        (copy.get("cta"), "display", 0.033, 0.027),
    ]
    available = h - 2 * margin if wide else round(h * 0.55) - margin

    def measure(scale):
        lines = []
        height = 0
        for value, role, ratio, spacing in groups:
            if not value:
                continue
            points = max(7, round(unit * ratio * scale))
            rows, ascent, descent, step = ts.measure(value, points, role, width - 3)
            block = max(4, ascent + descent + (len(rows) - 1) * step + 4)
            height += round(unit * spacing) if lines else 0
            lines.append((value, role, points, height, block))
            height += block
        return lines, height

    scale = 1.0
    lines, height = measure(scale)
    while height > available and scale > 0.22:
        scale *= 0.88
        lines, height = measure(scale)
    if height > available:
        raise LayoutOverflow("已确认的文字超出照片编排字区。")
    top = (h - height) // 2 if wide else h - margin - height
    photo = (0, 0, x - margin, h) if wide else (0, 0, w, top - margin)
    entries = [
        (value, role, points, (x, top + y, x + width, top + y + block))
        for value, role, points, y, block in lines
    ]
    return photo, entries
