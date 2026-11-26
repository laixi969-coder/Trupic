"""Parametric, non-templated commercial poster layout engine with infinite editorial variations.

Replaces repetitive templates and muddy Gaussian edge-stretching with combinatorial
editorial design axes:
  1. Architecture: full_bleed_scrim | editorial_split | floating_card | gallery_inset
  2. Anchor & flow: bottom | top | left | right (ratio-aware, with 9:16 safe zones)
  3. Adaptive palette: extracts vibrant product accent + clean editorial light/dark paper
  4. Typography voice: serif (editorial) vs display (modern sans) + bold numeric price anchor
  5. Graphic accents: hairline_rule | accent_bar | corner_ticks | brand_pill | clean
  6. Parametric proportions: continuous photo split (56%-68%) & margin rhythm (5%-8.5%)
"""

import hashlib
import math
import re

import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageStat

from .campaign import poster_footer
from .visual_review import LayoutOverflow

PRICE_RE = re.compile(r"[¥￥]?\d+(?:\.\d+)?\s*(?:元|折)(?:/[^\s，。；·]+)?")


def _seed_floats(seed_text, count=12):
    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    vals = []
    block = digest
    while len(vals) < count:
        for i in range(0, len(block), 2):
            vals.append(int.from_bytes(block[i : i + 2], "big") / 65535.0)
            if len(vals) >= count:
                break
        block = hashlib.sha256(block).digest()
    return vals


def _luma(rgb):
    r, g, b = (c / 255.0 for c in rgb[:3])
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(rgb1, rgb2):
    l1, l2 = _luma(rgb1), _luma(rgb2)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def extract_palette(photo, dark_bias=False):
    """Extract a disciplined 2-tone + 1-accent commercial palette from the hero photo."""
    if photo is None:
        return dict(
            paper=(247, 243, 235),
            ink=(24, 28, 25),
            muted=(92, 100, 94),
            accent=(188, 48, 44),
            accent_ink=(255, 251, 246),
            dark=False,
        )
    small = photo.convert("RGB").resize((64, 64), Image.Resampling.BILINEAR)
    arr = np.asarray(small, dtype=float).reshape(-1, 3)
    # Find high-saturation vivid pixels for brand/product accent (pick upper-quartile saturation)
    cmax = arr.max(axis=1)
    cmin = arr.min(axis=1)
    sat = (cmax - cmin) / np.maximum(cmax, 1.0)
    vivid = arr[(sat > 0.48) & (cmax > 70) & (cmax < 245)]
    if len(vivid) < 12:
        vivid = arr[(sat > 0.32) & (cmax > 55) & (cmax < 245)]
    if len(vivid) >= 12:
        accent_raw = np.median(vivid, axis=0)
    else:
        accent_raw = np.array([186.0, 52.0, 44.0])
    # Calibrate accent so it feels editorial, rich, never neon
    accent = tuple(int(np.clip(v, 24, 210)) for v in accent_raw)
    if _luma(accent) > 0.42:
        accent = tuple(int(v * 0.72) for v in accent)

    mean_rgb = arr.mean(axis=0)
    if dark_bias:
        # Deep luxury editorial surface subtly tinted toward the photo's hue
        base = np.array([18.0, 22.0, 20.0]) * 0.86 + mean_rgb * 0.14
        paper = tuple(int(np.clip(v, 14, 42)) for v in base)
        ink = (252, 248, 240)
        muted = (206, 202, 193)
        # Brighten accent slightly on dark surface for high contrast
        dark_accent = tuple(int(np.clip(v * 1.25 + 24, 90, 242)) for v in accent)
        accent_ink = (20, 20, 20) if _luma(dark_accent) > 0.4 else (255, 250, 244)
        return dict(
            paper=paper,
            ink=ink,
            muted=muted,
            accent=dark_accent,
            accent_ink=accent_ink,
            dark=True,
        )
    # Crisp warm archival editorial paper subtly harmonized with hero photo
    base = np.array([249.0, 246.0, 239.0]) * 0.94 + mean_rgb * 0.06
    paper = tuple(int(np.clip(v, 234, 252)) for v in base)
    ink = (22, 24, 22)
    muted = (82, 86, 82)
    accent_ink = (255, 251, 246) if _luma(accent) < 0.35 else (20, 20, 20)
    return dict(
        paper=paper,
        ink=ink,
        muted=muted,
        accent=accent,
        accent_ink=accent_ink,
        dark=False,
    )


def choose_recipe(size, seed_text, *, protected_subject=False, repair=False):
    """Sample a deterministic, high-taste layout recipe from continuous parametric axes."""
    w, h = size
    wide = w > h
    tall = h / max(w, 1) >= 1.55  # 9:16 story
    u = _seed_floats(seed_text, 12)

    if protected_subject:
        # Never crop away a merchant's real product photo or identityRegion
        archs = ("editorial_split", "gallery_inset")
    elif repair:
        # On typography repair, always guarantee rock-solid pure paper surface contrast
        archs = ("editorial_split",)
    else:
        archs = ("full_bleed_scrim", "editorial_split", "floating_card", "gallery_inset")
    arch = archs[int(u[0] * len(archs)) % len(archs)]

    if wide:
        anchors = ("left", "right")
    elif arch == "full_bleed_scrim":
        anchors = ("bottom", "top")
    elif arch == "floating_card":
        anchors = ("bottom", "top")
    else:
        anchors = ("bottom", "top")
    anchor = anchors[int(u[1] * len(anchors)) % len(anchors)]

    dark_bias = (u[2] > 0.52) if arch != "full_bleed_scrim" else True
    voice = "serif" if u[3] > 0.45 else "display"
    ornaments = ("hairline_rule", "accent_bar", "corner_ticks", "brand_pill", "clean")
    ornament = ornaments[int(u[4] * len(ornaments)) % len(ornaments)]

    # Continuous parametric split ratio & margin rhythm (truly infinite variations)
    split_ratio = 0.56 + u[5] * 0.11  # 56% - 67% hero photo area
    margin_ratio = 0.052 + u[6] * 0.026  # 5.2% - 7.8% breathing margin
    align = "center" if (not wide and arch in ("full_bleed_scrim", "editorial_split") and u[7] > 0.72) else "left"
    safe_top = 0.11 if tall else margin_ratio
    safe_bottom = 0.11 if tall else margin_ratio

    return dict(
        architecture=arch,
        anchor=anchor,
        dark=dark_bias,
        voice=voice,
        ornament=ornament,
        split=round(split_ratio, 3),
        margin=round(margin_ratio, 3),
        align=align,
        safeTop=round(safe_top, 3),
        safeBottom=round(safe_bottom, 3),
    )


def _apply_directional_scrim(image, anchor, tint=(14, 16, 15), coverage=0.48, strength=0.86):
    """Apply a silky, non-muddy optical gradient scrim ONLY over the typography zone."""
    w, h = image.size
    if anchor in ("bottom", "top"):
        y = np.linspace(0.0, 1.0, h)
        if anchor == "bottom":
            t = np.clip((y - (1.0 - coverage)) / max(coverage, 0.01), 0.0, 1.0)
        else:
            t = np.clip((coverage - y) / max(coverage, 0.01), 0.0, 1.0)
        # Smoothstep ease-in-out curve for seamless photographic transition
        alpha_1d = (t * t * (3.0 - 2.0 * t)) * (255.0 * strength)
        mask = Image.fromarray(np.uint8(np.broadcast_to(alpha_1d[:, None], (h, w))))
    else:
        x = np.linspace(0.0, 1.0, w)
        if anchor == "left":
            t = np.clip((coverage - x) / max(coverage, 0.01), 0.0, 1.0)
        else:
            t = np.clip((x - (1.0 - coverage)) / max(coverage, 0.01), 0.0, 1.0)
        alpha_1d = (t * t * (3.0 - 2.0 * t)) * (255.0 * strength)
        mask = Image.fromarray(np.uint8(np.broadcast_to(alpha_1d[None, :], (h, w))))
    overlay = Image.new("RGB", (w, h), tint)
    return Image.composite(overlay, image, mask)


def _fit_photo(photo, target_size, *, protect_full=False, backdrop_color=(247, 243, 235)):
    """Fill target_size edge-to-edge cleanly, or contain without blurry edges if protected."""
    tw, th = max(1, target_size[0]), max(1, target_size[1])
    rgb = photo.convert("RGB")
    if not protect_full:
        return ImageOps.fit(rgb, (tw, th), method=Image.Resampling.LANCZOS, centering=(0.5, 0.48)), (0, 0, tw, th)
    # Protected merchant photo: preserve 100% of pixels cleanly inside solid backdrop
    scale = min(tw / rgb.width, th / rgb.height)
    pw, ph = max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))
    resized = rgb.resize((pw, ph), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (tw, th), backdrop_color)
    ox, oy = (tw - pw) // 2, (th - ph) // 2
    canvas.paste(resized, (ox, oy))
    return canvas, (ox, oy, ox + pw, oy + ph)


def compose_editorial_poster(
    size,
    photo,
    ts,
    brand,
    copy,
    *,
    seed_text="",
    logo_path=None,
    protected_subject=False,
    repair=False,
    image_layers=None,
    kit=None,
):
    """Render an infinite-variation, commercial-magazine-grade poster without blurry edges."""
    w, h = size
    unit = min(w, h)
    wide = w > h
    kit = kit or {}
    recipe = choose_recipe(
        size,
        seed_text or f"{copy.get('title','')}|{w}x{h}",
        protected_subject=protected_subject,
        repair=repair,
    )
    pal = extract_palette(photo, dark_bias=recipe["dark"])
    if kit.get("color"):
        try:
            from PIL import ImageColor
            kc = ImageColor.getrgb(kit["color"])
            if _contrast(kc, pal["paper"]) >= 3.0:
                pal["accent"] = kc
                pal["accent_ink"] = (255, 251, 246) if _luma(kc) < 0.35 else (20, 20, 20)
        except ValueError:
            pass

    arch = recipe["architecture"]
    anchor = recipe["anchor"]
    margin = round(unit * recipe["margin"])
    top_pad = round(h * recipe["safeTop"])
    bot_pad = round(h * recipe["safeBottom"])

    # Clean brand name (never append clunky "创意场景示意")
    clean_brand = (brand or "").replace("创意场景示意", "").strip()
    title = (copy.get("title") or "").strip()
    subtitle = (copy.get("posterDeck") or copy.get("body") or "").strip()
    cta = (copy.get("cta") or "").strip()
    offer = (copy.get("offer") or "").strip()
    terms = (copy.get("terms") or "").strip()

    # Pull out distinct numeric price badge, and avoid repeating the same price across footer
    price_tag = ""
    if offer and PRICE_RE.search(offer):
        price_tag = PRICE_RE.search(offer).group(0).strip()
    elif m := PRICE_RE.search(subtitle):
        price_tag = m.group(0).strip()

    price_num = re.search(r"\d+(?:\.\d+)?", price_tag or "")
    has_price_in_text = bool(price_num and price_num.group(0) in (title + " " + subtitle))
    footer = poster_footer(copy, "" if has_price_in_text else offer, terms)
    if footer == cta:
        footer = cta

    # Build canvas & compute text_box + picture box cleanly
    scene = Image.new("RGB", (w, h), pal["paper"])
    box = None

    if photo is None:
        # Pure typographic Swiss-editorial poster (no photo)
        text_box = (margin, top_pad, w - margin, h - bot_pad)
        arch = "editorial_split"
    elif arch == "full_bleed_scrim":
        # Shift framing slightly away from the text anchor so the hero product stays unobstructed
        center = (0.5, 0.34) if (not wide and anchor == "bottom") else (0.5, 0.64) if (not wide and anchor == "top") else (0.5, 0.5)
        fitted = ImageOps.fit(photo.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS, centering=center)
        box = (0, 0, w, h)
        scrim_tint = (12, 14, 13)
        coverage = 0.45 if not wide else 0.52
        scene = _apply_directional_scrim(fitted, anchor, tint=scrim_tint, coverage=coverage, strength=0.92)
        pal["ink"] = (255, 251, 245)
        pal["muted"] = (224, 220, 212)
        if wide:
            tw = round(w * 0.44)
            text_box = (margin, margin, margin + tw, h - margin) if anchor == "left" else (w - margin - tw, margin, w - margin, h - margin)
        elif anchor == "top":
            text_box = (margin, top_pad, w - margin, round(h * 0.40))
        else:
            text_box = (margin, round(h * 0.60), w - margin, h - bot_pad)
    elif arch == "floating_card":
        fitted, box = _fit_photo(photo, (w, h), protect_full=False)
        scene = fitted
        card_pad = round(unit * 0.042)
        if wide:
            cw = round(w * 0.45)
            cx0 = margin if anchor == "left" else w - margin - cw
            card_rect = (cx0, margin, cx0 + cw, h - margin)
        elif anchor == "top":
            card_rect = (margin, top_pad, w - margin, round(h * 0.43))
        else:
            card_rect = (margin, round(h * 0.57), w - margin, h - bot_pad)
        # Draw soft frosted editorial card directly on scene
        card_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card_layer)
        rad = round(unit * 0.022)
        alpha = 242
        cd.rounded_rectangle(card_rect, radius=rad, fill=(*pal["paper"], alpha))
        border_col = (*pal["accent"], 120) if recipe["ornament"] == "hairline_rule" else (*pal["ink"], 36)
        cd.rounded_rectangle(card_rect, radius=rad, outline=border_col, width=max(1, round(unit * 0.002)))
        scene = Image.alpha_composite(scene.convert("RGBA"), card_layer).convert("RGB")
        text_box = (
            card_rect[0] + card_pad,
            card_rect[1] + card_pad,
            card_rect[2] - card_pad,
            card_rect[3] - card_pad,
        )
    elif arch == "gallery_inset":
        g_pad = round(unit * 0.068)
        if wide:
            pw = round((w - 3 * g_pad) * recipe["split"])
            if anchor == "left":
                p_rect = (w - g_pad - pw, g_pad, w - g_pad, h - g_pad)
                text_box = (g_pad, g_pad, p_rect[0] - g_pad, h - g_pad)
            else:
                p_rect = (g_pad, g_pad, g_pad + pw, h - g_pad)
                text_box = (p_rect[2] + g_pad, g_pad, w - g_pad, h - g_pad)
        else:
            ph = round((h - top_pad - bot_pad - g_pad) * recipe["split"])
            if anchor == "top":
                text_box = (g_pad, top_pad, w - g_pad, h - bot_pad - ph - round(g_pad * 0.7))
                p_rect = (g_pad, h - bot_pad - ph, w - g_pad, h - bot_pad)
            else:
                p_rect = (g_pad, top_pad, w - g_pad, top_pad + ph)
                text_box = (g_pad, p_rect[3] + round(g_pad * 0.75), w - g_pad, h - bot_pad)
        fitted, rel = _fit_photo(
            photo,
            (p_rect[2] - p_rect[0], p_rect[3] - p_rect[1]),
            protect_full=protected_subject,
            backdrop_color=pal["paper"],
        )
        scene.paste(fitted, p_rect[:2])
        box = (p_rect[0] + rel[0], p_rect[1] + rel[1], p_rect[0] + rel[2], p_rect[1] + rel[3])
        # Crisp 1.5px archival hairline frame
        sd = ImageDraw.Draw(scene)
        frame_pad = round(unit * 0.01)
        frame_col = tuple(int(c * 0.35 + pal["paper"][i] * 0.65) for i, c in enumerate(pal["ink"]))
        sd.rectangle(
            (p_rect[0] - frame_pad, p_rect[1] - frame_pad, p_rect[2] + frame_pad, p_rect[3] + frame_pad),
            outline=frame_col,
            width=max(1, round(unit * 0.002)),
        )
    else:
        # editorial_split: edge-to-edge crisp photo + pure harmonized typography panel
        if wide:
            pw = round(w * recipe["split"])
            if anchor == "left":
                p_rect = (w - pw, 0, w, h)
                text_box = (margin, margin, w - pw - margin, h - margin)
            else:
                p_rect = (0, 0, pw, h)
                text_box = (pw + margin, margin, w - margin, h - margin)
        else:
            ph = round(h * recipe["split"])
            if anchor == "top":
                p_rect = (0, h - ph, w, h)
                text_box = (margin, top_pad, w - margin, h - ph - round(margin * 0.7))
            else:
                p_rect = (0, 0, w, ph)
                text_box = (margin, ph + round(margin * 0.75), w - margin, h - bot_pad)
        fitted, rel = _fit_photo(
            photo,
            (p_rect[2] - p_rect[0], p_rect[3] - p_rect[1]),
            protect_full=protected_subject,
            backdrop_color=pal["paper"],
        )
        scene.paste(fitted, p_rect[:2])
        box = (p_rect[0] + rel[0], p_rect[1] + rel[1], p_rect[0] + rel[2], p_rect[1] + rel[3])
        # Subtle 2px accent hairline along the split seam
        sd = ImageDraw.Draw(scene)
        if wide:
            seam_x = p_rect[0] if anchor == "left" else p_rect[2]
            sd.line((seam_x, 0, seam_x, h), fill=pal["accent"], width=max(2, round(unit * 0.003)))
        else:
            seam_y = p_rect[1] if anchor == "top" else p_rect[3]
            sd.line((0, seam_y, w, seam_y), fill=pal["accent"], width=max(2, round(unit * 0.003)))

    if image_layers is not None:
        image_layers.append(("stage", scene.copy(), (0, 0)))

    # === Measure & Typeset Multi-Tier Typography with Editorial Precision ===
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    tx0, ty0, tx1, ty1 = text_box
    tw = max(40, tx1 - tx0)
    th = max(40, ty1 - ty0)

    # Smart headline wrapping on punctuation
    display_title = title
    base_title_pt = round(unit * (0.105 if not wide else 0.115))
    if ts.width(display_title.replace("\n", ""), base_title_pt, recipe["voice"]) > tw:
        display_title = re.sub(r"([，。！？：])(?=.)", r"\1\n", display_title, count=1)

    # Build ordered reading blocks: (kind, text, role, size_ratio, gap_ratio)
    blocks = []
    if clean_brand:
        blocks.append(("brand", clean_brand, "body", 0.028, 0.0))
    if display_title:
        blocks.append(("title", display_title, recipe["voice"], 0.098 if not wide else 0.105, 0.024))
    if subtitle:
        blocks.append(("sub", subtitle, "body", 0.036, 0.020))
    if footer and footer != subtitle:
        blocks.append(("cta", footer, "body", 0.030, 0.018))

    def measure_blocks(scale):
        measured = []
        y_cursor = 0
        for kind, text, role, ratio, gap in blocks:
            pts = max(14, round(unit * ratio * scale))
            rows, asc, desc, step = ts.measure(text, pts, role, tw - 6)
            bh = max(8, asc + desc + (len(rows) - 1) * step + 6)
            if measured:
                y_cursor += round(unit * gap * max(scale, 0.7))
            if kind == "brand" and recipe["ornament"] == "brand_pill":
                bh += round(unit * 0.014)
            measured.append((kind, text, role, pts, y_cursor, bh))
            y_cursor += bh
        return measured, y_cursor

    scale = 1.0
    measured, total_h = measure_blocks(scale)
    while total_h > th and scale > 0.35:
        scale *= 0.90
        measured, total_h = measure_blocks(scale)
    if total_h > th:
        raise LayoutOverflow("已确认的文字超出当前版式字区。")

    # Vertical placement inside text_box
    if anchor == "bottom" and arch == "full_bleed_scrim":
        start_y = ty1 - total_h
    elif anchor == "top" and arch == "full_bleed_scrim":
        start_y = ty0
    else:
        start_y = ty0 + max(0, (th - total_h) // 2)

    ink_hex = "#%02x%02x%02x" % pal["ink"]
    muted_hex = "#%02x%02x%02x" % pal["muted"]
    accent_hex = "#%02x%02x%02x" % pal["accent"]
    accent_ink_hex = "#%02x%02x%02x" % pal["accent_ink"]

    # Draw subtle graphic ornaments
    if recipe["ornament"] == "accent_bar":
        bar_w = max(4, round(unit * 0.007))
        draw.rectangle(
            (tx0, start_y, tx0 + bar_w, start_y + total_h),
            fill=(*pal["accent"], 235),
        )
        tx0 += bar_w + round(unit * 0.022)
        tw = max(40, tx1 - tx0)
    elif recipe["ornament"] == "corner_ticks" and arch != "full_bleed_scrim":
        tick = round(unit * 0.022)
        tc = (*pal["accent"], 190)
        lw = max(2, round(unit * 0.0025))
        draw.line((tx0, ty0, tx0 + tick, ty0), fill=tc, width=lw)
        draw.line((tx0, ty0, tx0, ty0 + tick), fill=tc, width=lw)
        draw.line((tx1 - tick, ty1, tx1, ty1), fill=tc, width=lw)
        draw.line((tx1, ty1 - tick, tx1, ty1), fill=tc, width=lw)

    # Render each typographic tier
    for kind, text, role, pts, rel_y, bh in measured:
        by0 = start_y + rel_y
        by1 = by0 + bh
        area = (tx0, by0, tx1, by1)
        if kind == "brand":
            if recipe["ornament"] == "brand_pill":
                bw = min(tw, round(ts.width(text, pts, role)) + round(unit * 0.036))
                px0 = tx0 if recipe["align"] == "left" else tx0 + (tw - bw) // 2
                draw.rounded_rectangle(
                    (px0, by0, px0 + bw, by1),
                    radius=round(bh / 2),
                    fill=(*pal["accent"], 235),
                )
                ts.draw(
                    draw,
                    text,
                    (px0 + round(unit * 0.018), by0 + round(unit * 0.005), px0 + bw, by1),
                    pts,
                    role,
                    accent_ink_hex,
                )
            else:
                ts.draw(draw, text, area, pts, role, accent_hex if not pal["dark"] else muted_hex, align=recipe["align"])
                if recipe["ornament"] == "hairline_rule":
                    rule_y = by1 + round(unit * 0.006)
                    rule_w = round(tw * 0.24)
                    rx0 = tx0 if recipe["align"] == "left" else tx0 + (tw - rule_w) // 2
                    draw.line((rx0, rule_y, rx0 + rule_w, rule_y), fill=(*pal["accent"], 210), width=max(2, round(unit * 0.0025)))
        elif kind == "title":
            ts.draw(draw, text, area, pts, role, ink_hex, align=recipe["align"])
        elif kind == "sub":
            ts.draw(draw, text, area, pts, role, ink_hex, align=recipe["align"])
        else:
            ts.draw(draw, text, area, pts, role, muted_hex, align=recipe["align"])

    # Dedicated high-contrast Price Anchor Pill (only on full-bleed / gallery where an open top corner exists, never overlapping bottom hero subjects)
    if price_tag and box and not protected_subject and arch in ("full_bleed_scrim", "gallery_inset") and anchor == "bottom":
        p_pts = max(24, round(unit * 0.042))
        pw_txt = round(ts.width(price_tag, p_pts, "numeric"))
        pad_x, pad_y = round(unit * 0.028), round(unit * 0.013)
        pill_w = pw_txt + 2 * pad_x
        pill_h = round(p_pts * 1.25) + 2 * pad_y
        px = (box[2] - round(unit * 0.03) - pill_w) if arch == "gallery_inset" else (w - margin - pill_w)
        py = (box[1] + round(unit * 0.03)) if arch == "gallery_inset" else top_pad
        draw.rounded_rectangle(
            (px, py, px + pill_w, py + pill_h),
            radius=round(pill_h / 2),
            fill=(*pal["accent"], 244),
        )
        ts.draw(
            draw,
            price_tag,
            (px + pad_x, py + pad_y, px + pill_w - pad_x, py + pill_h - pad_y),
            p_pts,
            "numeric",
            accent_ink_hex,
        )

    return scene, layer, box, recipe
