"""Measure the reading groups once for framed and full-bleed poster layouts."""

import re

from .visual_review import LayoutOverflow
from .campaign import poster_footer


def grid_layout(size, ts, brand, copy, detail, mode, first, *, body="", logo=False, has_picture=True):
    w, h = size
    unit = min(size)
    margin = round(unit * 0.05)
    wide = w > h
    framed = mode == "framed"
    split = round(w * (0.54 if first == "product" else 0.46))
    x = split if wide and not framed and has_picture else margin
    width = w - split - margin if wide and framed and has_picture else w - margin - x
    title = copy["title"]
    offer, terms = copy.get("offer"), copy.get("terms")
    # Bundle covers carry the complete merchant facts. Keep every non-duplicate clause.
    support = detail or re.split(r"[。！？]", copy.get("body", ""))[0]
    if body:
        displayed = {part.strip() for value in (brand, title, offer, terms, copy.get("cta"))
                     for part in re.split(r"[；;。]", value or "")}
        support = "；".join(part for part in re.split(r"[；;。]", body)
                           if part.strip() and part.strip() not in displayed)
    elif copy.get("writingSkill", {}).get("posterHeadings"):
        support = copy.get("body", "")
    elif offer:
        support = ""
    if support == terms:
        support = ""
    title_ratio = (0.21 if wide else 0.144) if first == "title" else 0.085
    title_size = round(unit * title_ratio)
    if ts.width(title.replace("\n", ""), title_size, "display") > width:
        title = re.sub(r"([，。！？：])(?=.)", r"\1\n", title, count=1)
    # The renderer keeps explicit lines and short headlines intact. Measure them
    # at their fitted width before reserving space for the photograph.
    if "\n" in title or len(title) <= 9:
        longest = max(ts.width(line, title_size, "display") for line in title.split("\n"))
        if longest > width - 3:
            title_size = max(7, int(title_size * (width - 4) / longest))
    # Each gap precedes its line. Price and conditions are read together.
    heading = (title, "display", title_size / unit, 0.021)
    deal = [(offer, "numeric", 0.17 if first == "offer" else 0.064, 0.020),
            (terms, "body", 0.036, 0.009)]
    groups = [(brand, "body", 0.029, 0)]
    if logo:
        groups.insert(0, ("logo", "logo", 0.065, 0))
    if copy.get("writingSkill", {}).get("posterHeadings"):
        groups.extend([heading, (support, "body", 0.040, 0.015),
                       (poster_footer(copy, offer, terms), "body", 0.032, 0.018)])
    else:
        if first == "offer" and offer:
            groups.extend(deal)
            if copy["title"] != offer:
                groups.append(heading)
        else:
            groups.append(heading)
            groups.extend(deal)
        groups.extend([(support, "body", 0.036, 0.015), (copy.get("cta"), "display", 0.033, 0.027)])
    available = h - 2 * margin if wide or not has_picture else round(h * 0.55) - margin

    def measure(scale):
        lines = []
        height = 0
        for value, role, ratio, spacing in groups:
            if not value:
                continue
            points = max(7, round(unit * ratio * scale))
            if role == "logo":
                block = points
            else:
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
    if wide or not has_picture:
        top = (h - height) // 2
        photo = (w - split + margin, margin, w - margin, h - margin) if framed else (0, 0, x - margin, h)
    elif framed:
        top = margin
        photo = (margin, top + height + margin, w - margin, h - margin)
    else:
        top = h - margin - height
        photo = (0, 0, w, top - margin)
    entries = [
        (value, role, points, (x, top + y, x + width, top + y + block))
        for value, role, points, y, block in lines
    ]
    return photo, entries
