"""Parametric, non-templated commercial poster layout engine with infinite editorial variations.

Combines and surpasses Artlook's modernist layout families & strict WCAG taste guardrails
with commercial product photography mastery:
  1. 12 Editorial Architectures:
     full_bleed_scrim | editorial_split | floating_card | gallery_inset |
     ledger | offset | monument | ribbon | edge | window | diagonal_bleed | diptych_focus
  2. 5 Taste Directions:
     international | editorial | eastern | material | high_energy
  3. Photo-Harmonic Palette + Strict WCAG Contrast Guardrails:
     title contrast >= 7.0:1, body contrast >= 4.5:1, dynamic scrim luminance calibration
  4. Typography Voice & Hierarchy:
     serif (editorial) vs display (modern sans) + dedicated non-overlapping numeric price anchor
  5. Graphic Accents & Protected-Subject Fidelity:
     hairline_rule | accent_bar | corner_ticks | brand_pill | index_tag | clean
     Zero cropping or occlusion of merchant-uploaded protected product photos.
  6. Continuous Parametric Proportions:
     Seed-driven split ratios, margin rhythms, color temperature, and alignment for infinite layouts.
"""

import hashlib
import re

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .campaign import poster_footer
from .visual_review import LayoutOverflow

PRICE_RE = re.compile(r"[¥￥]?\d+(?:\.\d+)?\s*(?:元|折)(?:/[^\s，。；·]+)?")

TITLE_MIN_CONTRAST = 7.0
BODY_MIN_CONTRAST = 4.5

DARK_INK = (10, 12, 14)
LIGHT_INK = (255, 253, 247)

ALL_ARCHITECTURES = (
    # 6 Full-Bleed Photography Families (全图大片)
    "full_bleed_scrim",
    "full_bleed_clean",
    "full_bleed_poster_type",
    "full_bleed_band",
    "full_bleed_editorial_edge",
    "floating_card",
    # 10 Architectural / Editorial Grid Families (现代平面与画册排版)
    "editorial_split",
    "gallery_inset",
    "ledger",
    "offset",
    "monument",
    "ribbon",
    "edge",
    "window",
    "diagonal_bleed",
    "diptych_focus",
)

FULL_BLEED_ARCHITECTURES = (
    "full_bleed_scrim",
    "full_bleed_clean",
    "full_bleed_poster_type",
    "full_bleed_band",
    "full_bleed_editorial_edge",
    "floating_card",
)

PROTECTED_ARCHITECTURES = (
    "editorial_split",
    "gallery_inset",
    "monument",
    "window",
)

TASTE_DIRECTIONS = (
    "international",
    "editorial",
    "eastern",
    "material",
    "high_energy",
)

# Artlook-inspired curated editorial grounds paired with photo-harmonic tinting
LIGHT_GROUNDS = (
    (246, 241, 232),  # Porcelain Clay
    (242, 240, 234),  # Redaction Off-White
    (243, 238, 235),  # Film Rose Paper
    (239, 241, 236),  # Linen Sage
)

DARK_GROUNDS = (
    (21, 20, 19),     # Espresso Obsidian
    (18, 23, 32),     # Midnight Slate
    (20, 29, 24),     # Deep Botanical
    (28, 21, 22),     # Smoked Burgundy
)


def _seed_floats(seed_text, count=16):
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


def _blend(c1, c2, t):
    return tuple(int(round(c1[i] * (1.0 - t) + c2[i] * t)) for i in range(3))


def _enforce_contrast(pal):
    """Artlook taste guardrail: guarantee >= 7:1 title contrast and >= 4.5:1 body contrast."""
    paper = pal["paper"]
    dark_paper = _luma(paper) < 0.35
    fallback_ink = LIGHT_INK if dark_paper else DARK_INK

    if _contrast(pal["ink"], paper) < TITLE_MIN_CONTRAST:
        pal["ink"] = fallback_ink

    # Ensure muted text clears 4.5:1 while keeping typographic hierarchy
    if _contrast(pal["muted"], paper) < BODY_MIN_CONTRAST:
        for step in (0.35, 0.55, 0.75, 1.0):
            cand = _blend(pal["muted"], pal["ink"], step)
            if _contrast(cand, paper) >= BODY_MIN_CONTRAST:
                pal["muted"] = cand
                break

    # Ensure accent_ink has crisp contrast over accent pill/band
    if _contrast(pal["accent_ink"], pal["accent"]) < BODY_MIN_CONTRAST:
        pal["accent_ink"] = LIGHT_INK if _contrast(LIGHT_INK, pal["accent"]) >= _contrast(DARK_INK, pal["accent"]) else DARK_INK

    pal["titleContrast"] = round(_contrast(pal["ink"], paper), 2)
    pal["bodyContrast"] = round(_contrast(pal["muted"], paper), 2)
    return pal


def extract_palette(photo, dark_bias=False, ground_variant=0):
    """Extract a photo-harmonic 2-tone + 1-accent editorial palette with WCAG contrast enforcement."""
    if photo is None:
        paper = DARK_GROUNDS[ground_variant % len(DARK_GROUNDS)] if dark_bias else LIGHT_GROUNDS[ground_variant % len(LIGHT_GROUNDS)]
        ink = (252, 249, 242) if dark_bias else (20, 22, 24)
        muted = (198, 194, 186) if dark_bias else (78, 82, 86)
        accent = (212, 74, 56) if dark_bias else (188, 48, 44)
        return _enforce_contrast(
            dict(
                paper=paper,
                ink=ink,
                muted=muted,
                accent=accent,
                accent_ink=(255, 251, 246),
                zone_tint=_blend(paper, accent, 0.14 if not dark_bias else 0.20),
                dark=dark_bias,
            )
        )

    small = photo.convert("RGB").resize((64, 64), Image.Resampling.BILINEAR)
    arr = np.asarray(small, dtype=float).reshape(-1, 3)
    cmax = arr.max(axis=1)
    cmin = arr.min(axis=1)
    sat = (cmax - cmin) / np.maximum(cmax, 1.0)
    # Lock onto the true hero chromatic hue (top saturation quartile) rather than averaging with neutral props/baskets
    valid_mask = (cmax > 65) & (cmax < 246) & (sat > 0.30)
    if valid_mask.sum() >= 16:
        sats_valid = sat[valid_mask]
        cutoff = max(0.45, float(np.percentile(sats_valid, 80)))
        vivid = arr[valid_mask & (sat >= cutoff)]
        if len(vivid) < 8:
            vivid = arr[valid_mask]
        accent_raw = np.median(vivid, axis=0)
    else:
        accent_raw = np.array([186.0, 52.0, 44.0])

    # Calibrate accent for editorial richness (deep crimson/cobalt/forest, never muddy or neon)
    accent = tuple(int(np.clip(v, 22, 214)) for v in accent_raw)
    if _luma(accent) > 0.38:
        accent = tuple(int(v * 0.74) for v in accent)

    mean_rgb = arr.mean(axis=0)
    warm = mean_rgb[0] >= mean_rgb[2]

    if dark_bias:
        pool = (DARK_GROUNDS[0], DARK_GROUNDS[3]) if warm else (DARK_GROUNDS[1], DARK_GROUNDS[2])
        ground = np.array(pool[ground_variant % len(pool)], dtype=float)
        base = ground * 0.88 + mean_rgb * 0.12
        paper = tuple(int(np.clip(v, 14, 38)) for v in base)
        ink = (252, 248, 241)
        muted = (204, 200, 192)
        dark_accent = tuple(int(np.clip(v * 1.24 + 22, 86, 238)) for v in accent)
        accent_ink = DARK_INK if _luma(dark_accent) > 0.36 else LIGHT_INK
        zone_tint = _blend(paper, dark_accent, 0.16)
        return _enforce_contrast(
            dict(
                paper=paper,
                ink=ink,
                muted=muted,
                accent=dark_accent,
                accent_ink=accent_ink,
                zone_tint=zone_tint,
                dark=True,
            )
        )

    pool = (LIGHT_GROUNDS[0], LIGHT_GROUNDS[2], LIGHT_GROUNDS[1]) if warm else (LIGHT_GROUNDS[1], LIGHT_GROUNDS[3], LIGHT_GROUNDS[0])
    ground = np.array(pool[ground_variant % len(pool)], dtype=float)
    base = ground * 0.94 + mean_rgb * 0.06
    paper = tuple(int(np.clip(v, 234, 252)) for v in base)
    ink = (20, 22, 24)
    muted = (76, 80, 82)
    accent_ink = LIGHT_INK if _luma(accent) < 0.34 else DARK_INK
    zone_tint = _blend(paper, accent, 0.11)
    return _enforce_contrast(
        dict(
            paper=paper,
            ink=ink,
            muted=muted,
            accent=accent,
            accent_ink=accent_ink,
            zone_tint=zone_tint,
            dark=False,
        )
    )


def choose_recipe(size, seed_text, *, protected_subject=False, repair=False, architecture=None):
    """Sample a deterministic, high-taste layout recipe from 12+ families and continuous axes."""
    w, h = size
    wide = w > h
    tall = h / max(w, 1) >= 1.55  # 9:16 story
    u = _seed_floats(seed_text, 16)

    if architecture and architecture in ALL_ARCHITECTURES:
        if protected_subject and architecture not in PROTECTED_ARCHITECTURES:
            arch = PROTECTED_ARCHITECTURES[int(u[0] * len(PROTECTED_ARCHITECTURES)) % len(PROTECTED_ARCHITECTURES)]
        else:
            arch = architecture
    elif protected_subject:
        arch = PROTECTED_ARCHITECTURES[int(u[0] * len(PROTECTED_ARCHITECTURES)) % len(PROTECTED_ARCHITECTURES)]
    elif repair:
        archs = ("editorial_split", "ribbon", "monument")
        arch = archs[int(u[0] * len(archs)) % len(archs)]
    else:
        arch = ALL_ARCHITECTURES[int(u[0] * len(ALL_ARCHITECTURES)) % len(ALL_ARCHITECTURES)]

    if wide:
        anchors = ("left", "right")
    elif arch in ("edge", "ledger", "offset", "full_bleed_editorial_edge"):
        anchors = ("left", "right")
    else:
        anchors = ("bottom", "top")
    anchor = anchors[int(u[1] * len(anchors)) % len(anchors)]

    taste_map = {
        "ledger": "international",
        "edge": "international",
        "full_bleed_editorial_edge": "international",
        "offset": "high_energy",
        "diagonal_bleed": "high_energy",
        "full_bleed_poster_type": "high_energy",
        "monument": "eastern",
        "window": "eastern",
        "full_bleed_clean": "eastern",
        "gallery_inset": "editorial",
        "ribbon": "editorial",
        "full_bleed_scrim": "editorial",
        "full_bleed_band": "editorial",
        "diptych_focus": "material",
        "floating_card": "material",
        "editorial_split": TASTE_DIRECTIONS[int(u[8] * len(TASTE_DIRECTIONS)) % len(TASTE_DIRECTIONS)],
    }
    taste = taste_map.get(arch, "editorial")

    if arch in ("full_bleed_scrim", "full_bleed_clean", "full_bleed_poster_type"):
        dark_bias = True
    elif arch in ("ledger", "monument", "ribbon"):
        dark_bias = u[2] > 0.72  # mostly crisp archival paper, occasionally dramatic dark
    else:
        dark_bias = u[2] > 0.54

    if taste in ("eastern", "editorial"):
        voice = "serif" if u[3] > 0.25 else "display"
    elif taste in ("international", "high_energy"):
        voice = "display" if u[3] > 0.28 else "serif"
    else:
        voice = "serif" if u[3] > 0.48 else "display"

    ornaments = ("hairline_rule", "accent_bar", "corner_ticks", "brand_pill", "index_tag", "clean")
    ornament = ornaments[int(u[4] * len(ornaments)) % len(ornaments)]

    # Continuous parametric proportions (truly infinite variations)
    split_ratio = 0.55 + u[5] * 0.11  # 55% - 66%
    margin_ratio = 0.050 + u[6] * 0.024  # 5.0% - 7.4%
    if arch in ("monument", "ribbon"):
        align = "center"
    elif arch in ("ledger", "edge", "diagonal_bleed", "window"):
        align = "left"
    elif arch == "offset":
        align = "right" if anchor == "right" else "left"
    else:
        align = "center" if (not wide and arch in ("full_bleed_scrim", "editorial_split") and u[7] > 0.72) else "left"

    safe_top = 0.105 if tall else margin_ratio
    safe_bottom = 0.105 if tall else margin_ratio
    ground_variant = int(u[9] * 4) % 4
    serial_no = f"NO.{int(u[10] * 89 + 10):02d}"

    return dict(
        architecture=arch,
        taste=taste,
        anchor=anchor,
        dark=dark_bias,
        voice=voice,
        ornament=ornament,
        split=round(split_ratio, 3),
        margin=round(margin_ratio, 3),
        align=align,
        safeTop=round(safe_top, 3),
        safeBottom=round(safe_bottom, 3),
        groundVariant=ground_variant,
        serial=serial_no,
    )


def _quiet_vertical_anchor(photo):
    """Detect whether the top or bottom third of the hero photo has lower visual clutter (negative space)."""
    small = photo.convert("RGB").resize((64, 64), Image.Resampling.BILINEAR)
    arr = np.asarray(small, dtype=float)
    # Gradient edge energy + color saturation = visual busyness / hero saliency
    gx = np.abs(np.diff(arr, axis=1)).mean(axis=2)
    gy = np.abs(np.diff(arr, axis=0)).mean(axis=2)
    energy = gx[:63, :63] + gy[:63, :63]
    cmax = arr[:63, :63].max(axis=2)
    cmin = arr[:63, :63].min(axis=2)
    sat = (cmax - cmin) / np.maximum(cmax, 1.0)
    saliency = energy + sat * 45.0
    top_score = float(saliency[:22, :].mean())
    bot_score = float(saliency[41:, :].mean())
    return "top" if top_score <= bot_score else "bottom"


def _apply_directional_scrim(image, anchor, tint=(12, 14, 13), coverage=0.46, strength=0.90):
    """Apply a silky smoothstep optical gradient scrim ONLY over the typography zone."""
    w, h = image.size
    if anchor in ("bottom", "top"):
        y = np.linspace(0.0, 1.0, h)
        t = (
            np.clip((y - (1.0 - coverage)) / max(coverage, 0.01), 0.0, 1.0)
            if anchor == "bottom"
            else np.clip((coverage - y) / max(coverage, 0.01), 0.0, 1.0)
        )
        alpha_1d = (t * t * (3.0 - 2.0 * t)) * (255.0 * strength)
        mask = Image.fromarray(np.uint8(np.broadcast_to(alpha_1d[:, None], (h, w))))
    else:
        x = np.linspace(0.0, 1.0, w)
        t = (
            np.clip((coverage - x) / max(coverage, 0.01), 0.0, 1.0)
            if anchor == "left"
            else np.clip((x - (1.0 - coverage)) / max(coverage, 0.01), 0.0, 1.0)
        )
        alpha_1d = (t * t * (3.0 - 2.0 * t)) * (255.0 * strength)
        mask = Image.fromarray(np.uint8(np.broadcast_to(alpha_1d[None, :], (h, w))))
    overlay = Image.new("RGB", (w, h), tint)
    return Image.composite(overlay, image, mask)


def _fit_photo(photo, target_size, *, protect_full=False, backdrop_color=(246, 241, 232), centering=(0.5, 0.48)):
    """Fill target_size edge-to-edge cleanly, or contain without blurry edges if protected."""
    tw, th = max(1, target_size[0]), max(1, target_size[1])
    rgb = photo.convert("RGB")
    if not protect_full:
        return ImageOps.fit(rgb, (tw, th), method=Image.Resampling.LANCZOS, centering=centering), (0, 0, tw, th)
    scale = min(tw / rgb.width, th / rgb.height)
    pw, ph = max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))
    resized = rgb.resize((pw, ph), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (tw, th), backdrop_color)
    ox, oy = (tw - pw) // 2, (th - ph) // 2
    canvas.paste(resized, (ox, oy))
    return canvas, (ox, oy, ox + pw, oy + ph)


def _crop_macro_detail(photo, target_size):
    """Extract a rich zoomed macro detail crop locked onto the most chromatic hero focal area."""
    rgb = photo.convert("RGB")
    pw, ph = rgb.size
    small = rgb.resize((48, 48), Image.Resampling.BILINEAR)
    arr = np.asarray(small, dtype=float)
    cmax = arr.max(axis=2)
    cmin = arr.min(axis=2)
    sat = (cmax - cmin) / np.maximum(cmax, 1.0)
    # Weight center slightly while strongly locking onto saturated product regions (e.g. berries, dish, garment)
    yy, xx = np.mgrid[0:48, 0:48]
    center_w = np.exp(-(((xx - 24) / 22.0) ** 2 + ((yy - 24) / 22.0) ** 2))
    weight = np.where((cmax > 55) & (sat > 0.35), (sat ** 2) * center_w, 0.0)
    if weight.sum() > 0.05:
        cx = float((xx * weight).sum() / weight.sum()) / 48.0
        cy = float((yy * weight).sum() / weight.sum()) / 48.0
    else:
        cx, cy = 0.5, 0.52
    # Tight 46% macro window around the vivid product focal centroid
    win_w = max(64, round(pw * 0.46))
    win_h = max(64, round(ph * 0.46))
    x0 = int(np.clip(round(cx * pw - win_w / 2), 0, max(0, pw - win_w)))
    y0 = int(np.clip(round(cy * ph - win_h / 2), 0, max(0, ph - win_h)))
    cropped = rgb.crop((x0, y0, x0 + win_w, y0 + win_h))
    return ImageOps.fit(cropped, (max(1, target_size[0]), max(1, target_size[1])), method=Image.Resampling.LANCZOS)


def _strip_price_from_subtitle(subtitle, price_tag):
    """Avoid repeating the exact price inside subtitle when a dedicated Price Anchor Badge displays it."""
    if not subtitle or not price_tag or price_tag not in subtitle:
        return subtitle
    cleaned = subtitle.replace(price_tag, "").strip(" ·，,。/|-")
    cleaned = re.sub(r"\s*·\s*·\s*", " · ", cleaned)
    return cleaned if len(cleaned) >= 4 else subtitle


def _paste_arch_window(scene, fitted, rect, radius):
    """Paste photo through a clean top-arch architectural aperture mask."""
    x0, y0, x1, y1 = rect
    rw, rh = x1 - x0, y1 - y0
    mask = Image.new("L", (rw, rh), 0)
    md = ImageDraw.Draw(mask)
    r = min(radius, rw // 2, rh // 2)
    md.pieslice((0, 0, r * 2, r * 2), 180, 270, fill=255)
    md.pieslice((rw - r * 2, 0, rw, r * 2), 270, 360, fill=255)
    md.rectangle((r, 0, rw - r, r), fill=255)
    md.rectangle((0, r, rw, rh), fill=255)
    scene.paste(fitted, (x0, y0), mask)


def _draw_price_badge(draw, ts, price_tag, pal, unit, anchor_x, anchor_y, *, align="right", scale=1.0):
    """Draw a high-contrast, collision-free numeric price anchor badge."""
    if not price_tag:
        return None
    p_pts = max(22, round(unit * 0.042 * scale))
    pw_txt = round(ts.width(price_tag, p_pts, "numeric"))
    pad_x, pad_y = round(unit * 0.026 * scale), round(unit * 0.012 * scale)
    pill_w = pw_txt + 2 * pad_x
    pill_h = round(p_pts * 1.24) + 2 * pad_y
    if align == "right":
        px = anchor_x - pill_w
    elif align == "center":
        px = anchor_x - pill_w // 2
    else:
        px = anchor_x
    py = anchor_y
    draw.rounded_rectangle(
        (px, py, px + pill_w, py + pill_h),
        radius=round(pill_h / 2),
        fill=(*pal["accent"], 245),
    )
    accent_ink_hex = "#%02x%02x%02x" % pal["accent_ink"]
    ts.draw(
        draw,
        price_tag,
        (px + pad_x, py + pad_y, px + pill_w - pad_x, py + pill_h - pad_y),
        p_pts,
        "numeric",
        accent_ink_hex,
    )
    return (px, py, px + pill_w, py + pill_h)


def _typeset_block(draw, ts, text_box, blocks, pal, recipe, unit, *, v_align="center", align_override=None):
    """Measure, auto-fit, and draw multi-tier typography inside text_box with zero overflow."""
    tx0, ty0, tx1, ty1 = text_box
    tw = max(40, tx1 - tx0)
    th = max(36, ty1 - ty0)
    align = align_override or recipe["align"]

    def measure_blocks(scale):
        measured = []
        y_cursor = 0
        for kind, text, role, ratio, gap in blocks:
            pts = max(13, round(unit * ratio * scale))
            rows, asc, desc, step = ts.measure(text, pts, role, tw - 6)
            bh = max(8, asc + desc + (len(rows) - 1) * step + 6)
            if measured:
                y_cursor += round(unit * gap * max(scale, 0.65))
            if kind == "brand" and recipe["ornament"] == "brand_pill":
                bh += round(unit * 0.014)
            measured.append((kind, text, role, pts, y_cursor, bh))
            y_cursor += bh
        return measured, y_cursor

    scale = 1.0
    measured, total_h = measure_blocks(scale)
    while total_h > th and scale > 0.34:
        scale *= 0.90
        measured, total_h = measure_blocks(scale)
    if total_h > th:
        raise LayoutOverflow("已确认的文字超出当前版式字区。")

    if v_align == "bottom":
        start_y = ty1 - total_h
    elif v_align == "top":
        start_y = ty0
    else:
        start_y = ty0 + max(0, (th - total_h) // 2)

    ink_hex = "#%02x%02x%02x" % pal["ink"]
    muted_hex = "#%02x%02x%02x" % pal["muted"]
    accent_hex = "#%02x%02x%02x" % pal["accent"]
    accent_ink_hex = "#%02x%02x%02x" % pal["accent_ink"]

    if recipe["ornament"] == "accent_bar" and align == "left":
        bar_w = max(4, round(unit * 0.007))
        draw.rectangle(
            (tx0, start_y, tx0 + bar_w, start_y + total_h),
            fill=(*pal["accent"], 235),
        )
        tx0 += bar_w + round(unit * 0.020)
        tw = max(40, tx1 - tx0)

    for kind, text, role, pts, rel_y, bh in measured:
        by0 = start_y + rel_y
        by1 = by0 + bh
        area = (tx0, by0, tx1, by1)
        if kind == "brand":
            pill_pad = round(unit * 0.036)
            fits_pill = recipe["ornament"] == "brand_pill" and (round(ts.width(text, pts, role)) + pill_pad <= tw)
            if fits_pill:
                bw = round(ts.width(text, pts, role)) + pill_pad
                if align == "center":
                    px0 = tx0 + (tw - bw) // 2
                elif align == "right":
                    px0 = tx1 - bw
                else:
                    px0 = tx0
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
                brand_color = accent_hex if (not pal["dark"] and _contrast(pal["accent"], pal["paper"]) >= 4.0) else muted_hex
                ts.draw(draw, text, area, pts, role, brand_color, align=align)
                if recipe["ornament"] == "hairline_rule":
                    rule_y = by1 + round(unit * 0.005)
                    rule_w = round(tw * 0.22)
                    if align == "center":
                        rx0 = tx0 + (tw - rule_w) // 2
                    elif align == "right":
                        rx0 = tx1 - rule_w
                    else:
                        rx0 = tx0
                    draw.line((rx0, rule_y, rx0 + rule_w, rule_y), fill=(*pal["accent"], 210), width=max(2, round(unit * 0.0024)))
        elif kind == "title":
            ts.draw(draw, text, area, pts, role, ink_hex, align=align)
        elif kind == "sub":
            ts.draw(draw, text, area, pts, role, ink_hex, align=align)
        else:
            ts.draw(draw, text, area, pts, role, muted_hex, align=align)

    return (tx0, start_y, tx1, start_y + total_h)


def _smart_wrap_title(ts, title, max_width, base_pt, voice):
    if not title:
        return ""
    if ts.width(title.replace("\n", ""), base_pt, voice) <= max_width:
        return title
    if re.search(r"[，。！？：]", title):
        return re.sub(r"([，。！？：])(?=.)", r"\1\n", title, count=1)
    return title


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
    architecture=None,
):
    """Render an infinite-variation, art-director-grade commercial poster."""
    w, h = size
    unit = min(w, h)
    wide = w > h
    kit = kit or {}
    recipe = choose_recipe(
        size,
        seed_text or f"{copy.get('title','')}|{w}x{h}",
        protected_subject=protected_subject,
        repair=repair,
        architecture=architecture,
    )
    pal = extract_palette(photo, dark_bias=recipe["dark"], ground_variant=recipe["groundVariant"])
    if kit.get("color"):
        try:
            from PIL import ImageColor

            kc = ImageColor.getrgb(kit["color"])
            if _contrast(kc, pal["paper"]) >= 3.0:
                pal["accent"] = kc
                pal["accent_ink"] = LIGHT_INK if _luma(kc) < 0.35 else DARK_INK
                pal["zone_tint"] = _blend(pal["paper"], kc, 0.12 if not pal["dark"] else 0.18)
                pal = _enforce_contrast(pal)
        except ValueError:
            pass

    arch = recipe["architecture"]
    anchor = recipe["anchor"]
    margin = round(unit * recipe["margin"])
    top_pad = round(h * recipe["safeTop"])
    bot_pad = round(h * recipe["safeBottom"])

    clean_brand = (brand or "").replace("创意场景示意", "").strip()
    title = (copy.get("title") or "").strip()
    subtitle = (copy.get("posterDeck") or copy.get("body") or "").strip()
    cta = (copy.get("cta") or "").strip()
    offer = (copy.get("offer") or "").strip()
    terms = (copy.get("terms") or "").strip()

    price_tag = ""
    if offer and PRICE_RE.search(offer):
        price_tag = PRICE_RE.search(offer).group(0).strip()
    elif m := PRICE_RE.search(subtitle):
        price_tag = m.group(0).strip()

    price_num = re.search(r"\d+(?:\.\d+)?", price_tag or "")
    has_price_in_text = bool(price_num and price_num.group(0) in (title + " " + subtitle))
    footer = poster_footer(copy, "" if has_price_in_text else offer, terms)

    # Determine whether this architecture renders a dedicated high-contrast Price Anchor Badge
    shows_price_badge = bool(
        price_tag
        and photo is not None
        and (
            (arch == "gallery_inset" and not protected_subject and anchor == "bottom" and not wide)
            or (arch in ("full_bleed_scrim", "floating_card") and not protected_subject and not wide)
            or (arch in ("full_bleed_clean", "full_bleed_poster_type", "full_bleed_band", "full_bleed_editorial_edge") and not protected_subject)
            or (arch in ("ledger", "edge"))
            or (arch in ("offset", "ribbon", "window", "diagonal_bleed", "diptych_focus") and not wide)
        )
    )
    display_subtitle = _strip_price_from_subtitle(subtitle, price_tag) if shows_price_badge else subtitle

    scene = Image.new("RGB", (w, h), pal["paper"])
    sd = ImageDraw.Draw(scene)
    box = None
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    hair_col = _blend(pal["ink"], pal["paper"], 0.72)
    hair_w = max(1, round(unit * 0.002))

    # Helper to build standard block tuples
    def standard_blocks(max_tw, title_ratio=0.095, include_brand=True, include_sub=True, include_cta=True, sub_ratio=0.035):
        blocks = []
        if include_brand and clean_brand:
            blocks.append(("brand", clean_brand, "body", 0.027, 0.0))
        if title:
            dt = _smart_wrap_title(ts, title, max_tw, round(unit * title_ratio), recipe["voice"])
            blocks.append(("title", dt, recipe["voice"], title_ratio, 0.022))
        if include_sub and display_subtitle:
            blocks.append(("sub", display_subtitle, "body", sub_ratio, 0.019))
        if include_cta and footer and footer != display_subtitle:
            blocks.append(("cta", footer, "body", 0.029, 0.016))
        return blocks

    if photo is None:
        # Pure typographic Swiss-editorial poster
        text_box = (margin, top_pad, w - margin, h - bot_pad)
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        _typeset_block(draw, ts, text_box, standard_blocks(w - 2 * margin, 0.11), pal, recipe, unit)
        recipe["titleContrast"] = pal["titleContrast"]
        return scene, layer, box, recipe

    # ==================== 16 ARCHITECTURAL FAMILIES ====================

    if arch == "full_bleed_scrim":
        fitted = ImageOps.fit(photo.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        box = (0, 0, w, h)
        eff_anchor = anchor if wide else _quiet_vertical_anchor(fitted)
        probe_y = (round(h * 0.62), h) if eff_anchor == "bottom" else (0, round(h * 0.38))
        zone_luma = float(np.asarray(fitted.crop((0, probe_y[0], w, probe_y[1])).resize((24, 24))).mean()) / 255.0
        scrim_strength = float(np.clip(0.84 + zone_luma * 0.12, 0.84, 0.95))
        scene = _apply_directional_scrim(fitted, eff_anchor, tint=(10, 12, 11), coverage=0.44 if not wide else 0.52, strength=scrim_strength)
        pal["ink"] = (255, 252, 246)
        pal["muted"] = (228, 224, 216)
        pal["paper"] = (14, 16, 15)
        pal = _enforce_contrast(pal)
        if wide:
            tw = round(w * 0.44)
            text_box = (margin, margin, margin + tw, h - margin) if eff_anchor == "left" else (w - margin - tw, margin, w - margin, h - margin)
        elif eff_anchor == "top":
            text_box = (margin, top_pad, w - margin, round(h * 0.38))
        else:
            text_box = (margin, round(h * 0.59), w - margin, h - bot_pad)
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        v_al = "bottom" if (not wide and eff_anchor == "bottom") else "top" if (not wide and eff_anchor == "top") else "center"
        _typeset_block(draw, ts, text_box, standard_blocks(text_box[2] - text_box[0], 0.098), pal, recipe, unit, v_align=v_al)
        if price_tag and not protected_subject and not wide:
            py_badge = top_pad if eff_anchor == "bottom" else (h - bot_pad - round(unit * 0.072))
            _draw_price_badge(draw, ts, price_tag, pal, unit, w - margin, py_badge, align="right")

    elif arch == "full_bleed_clean":
        # Pure breathing full-bleed photography (Aesop / Kinfolk style): auto-locks onto photo's quietest zone
        fitted = ImageOps.fit(photo.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        box = (0, 0, w, h)
        quiet = anchor if wide else _quiet_vertical_anchor(fitted)
        probe = (
            fitted.crop((0, 0, w, round(h * 0.36))) if quiet == "top"
            else fitted.crop((0, round(h * 0.64), w, h)) if quiet == "bottom"
            else fitted.crop((0, 0, round(w * 0.45), h)) if quiet == "left"
            else fitted.crop((round(w * 0.55), 0, w, h))
        )
        zone_luma = float(np.asarray(probe.resize((24, 24))).mean()) / 255.0
        # Whisper-light gradient scrim only strong enough to ensure 7:1 crisp typography without darkening the subject
        scrim_strength = float(np.clip(0.46 + zone_luma * 0.38, 0.48, 0.82))
        scene = _apply_directional_scrim(fitted, quiet, tint=(12, 13, 12), coverage=0.40 if not wide else 0.48, strength=scrim_strength)
        # Subtle bottom anchor feather for bottom colophon when title is on top
        if not wide and quiet == "top":
            scene = _apply_directional_scrim(scene, "bottom", tint=(12, 13, 12), coverage=0.18, strength=0.68)
        pal["ink"] = (255, 253, 248)
        pal["muted"] = (232, 228, 220)
        pal["paper"] = (16, 17, 16)
        pal = _enforce_contrast(pal)
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        if wide:
            tw = round(w * 0.42)
            text_box = (margin, margin, margin + tw, h - margin) if quiet == "left" else (w - margin - tw, margin, w - margin, h - margin)
            _typeset_block(draw, ts, text_box, standard_blocks(tw, 0.096), pal, recipe, unit, v_align="center", align_override="left")
            if price_tag and not protected_subject:
                _draw_price_badge(draw, ts, price_tag, pal, unit, w - margin if quiet == "left" else margin, margin, align="right" if quiet == "left" else "left")
        elif quiet == "top":
            # Headline floats cleanly in the quiet upper third; crisp cinema colophon anchors the bottom edge
            head_blocks = standard_blocks(w - 2 * margin, 0.098, include_brand=True, include_sub=False, include_cta=False)
            _typeset_block(draw, ts, (margin, top_pad, w - margin, round(h * 0.36)), head_blocks, pal, recipe, unit, v_align="top", align_override="left")
            bot_blocks = []
            if display_subtitle:
                bot_blocks.append(("sub", display_subtitle, "body", 0.034, 0.0))
            if footer and footer != display_subtitle:
                bot_blocks.append(("cta", footer, "body", 0.028, 0.012))
            if price_tag and not protected_subject:
                _draw_price_badge(draw, ts, price_tag, pal, unit, w - margin, h - bot_pad - round(unit * 0.072), align="right", scale=0.92)
                if bot_blocks:
                    _typeset_block(draw, ts, (margin, round(h * 0.84), w - margin - round(unit * 0.34), h - bot_pad), bot_blocks, pal, recipe, unit, v_align="bottom", align_override="left")
            elif bot_blocks:
                _typeset_block(draw, ts, (margin, round(h * 0.84), w - margin, h - bot_pad), bot_blocks, pal, recipe, unit, v_align="bottom", align_override="left")
        else:
            _typeset_block(draw, ts, (margin, round(h * 0.60), w - margin, h - bot_pad), standard_blocks(w - 2 * margin, 0.096), pal, recipe, unit, v_align="bottom", align_override="left")
            if price_tag and not protected_subject:
                _draw_price_badge(draw, ts, price_tag, pal, unit, w - margin, top_pad, align="right")

    elif arch == "full_bleed_poster_type":
        # Magazine Cover Full-Bleed (Vogue / Kinfolk): monumental centered cover title on top + sleek bottom caption bar
        fitted = ImageOps.fit(photo.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.54))
        box = (0, 0, w, h)
        scene = _apply_directional_scrim(fitted, "top", tint=(10, 11, 11), coverage=0.38 if not wide else 0.44, strength=0.76)
        scene = _apply_directional_scrim(scene, "bottom", tint=(10, 11, 11), coverage=0.20 if not wide else 0.24, strength=0.82)
        pal["ink"] = (255, 253, 248)
        pal["muted"] = (232, 228, 222)
        pal["paper"] = (12, 13, 13)
        pal = _enforce_contrast(pal)
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        # Monumental cover headline in upper third
        head_blocks = standard_blocks(w - 2 * margin, 0.110 if not wide else 0.100, include_brand=True, include_sub=False, include_cta=False)
        _typeset_block(draw, ts, (margin, top_pad, w - margin, round(h * (0.37 if not wide else 0.45))), head_blocks, pal, recipe, unit, v_align="top", align_override="center")
        # Sleek bottom hairline + cinema caption row
        cap_y0 = round(h * (0.85 if not wide else 0.78))
        draw.line((margin, cap_y0 - round(unit * 0.012), w - margin, cap_y0 - round(unit * 0.012)), fill=(255, 252, 246, 135), width=max(1, round(unit * 0.0018)))
        bot_blocks = []
        if display_subtitle:
            bot_blocks.append(("sub", display_subtitle, "body", 0.034, 0.0))
        if footer and footer != display_subtitle:
            bot_blocks.append(("cta", footer, "body", 0.028, 0.010))
        if price_tag and not protected_subject:
            _draw_price_badge(draw, ts, price_tag, pal, unit, w - margin, cap_y0 + max(0, (h - bot_pad - cap_y0 - round(unit * 0.068)) // 2), align="right", scale=0.90)
            cta_x1 = w - margin - round(unit * 0.34)
        else:
            cta_x1 = w - margin
        if bot_blocks:
            _typeset_block(draw, ts, (margin, cap_y0, max(margin + 120, cta_x1), h - bot_pad), bot_blocks, pal, recipe, unit, v_align="center", align_override="left")

    elif arch == "full_bleed_band":
        # Full-bleed edge-to-edge photo with an architectural frosted translucent editorial waist-band
        fitted = ImageOps.fit(photo.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        box = (0, 0, w, h)
        quiet = _quiet_vertical_anchor(fitted) if not wide else "bottom"
        if wide:
            band_y0, band_y1 = round(h * 0.62), round(h * 0.92)
        elif quiet == "top":
            band_y0, band_y1 = top_pad + round(unit * 0.01), round(h * 0.34)
        else:
            band_y0, band_y1 = round(h * 0.64), h - bot_pad
        band_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        bd = ImageDraw.Draw(band_layer)
        bd.rectangle((0, band_y0, w, band_y1), fill=(*pal["paper"], 226))
        bd.line((0, band_y0, w, band_y0), fill=(*pal["accent"], 235), width=max(2, round(unit * 0.0028)))
        bd.line((0, band_y1, w, band_y1), fill=(*pal["accent"], 235), width=max(2, round(unit * 0.0028)))
        scene = Image.alpha_composite(fitted.convert("RGBA"), band_layer).convert("RGB")
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        pad_y = round(unit * 0.026)
        if price_tag and not protected_subject:
            _draw_price_badge(draw, ts, price_tag, pal, unit, w - margin, band_y0 + max(pad_y, (band_y1 - band_y0 - round(unit * 0.072)) // 2), align="right", scale=0.94)
            tx1 = w - margin - round(unit * 0.34)
        else:
            tx1 = w - margin
        band_blocks = standard_blocks(max(120, tx1 - margin), 0.084 if not wide else 0.078, include_brand=True, include_sub=True, include_cta=True, sub_ratio=0.032)
        _typeset_block(draw, ts, (margin, band_y0 + pad_y, max(margin + 120, tx1), band_y1 - pad_y), band_blocks, pal, recipe, unit, v_align="center", align_override="left")

    elif arch == "full_bleed_editorial_edge":
        # Full-bleed edge-to-edge photography + tall architectural frosted glass side column
        fitted = ImageOps.fit(photo.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS, centering=(0.64 if anchor == "left" else 0.36, 0.5))
        box = (0, 0, w, h)
        col_w = round(w * (0.40 if wide else 0.45))
        if anchor == "left":
            col_rect = (0, 0, col_w, h)
            seam_x = col_w
            text_box = (margin, top_pad, col_w - round(margin * 0.7), h - bot_pad)
        else:
            col_rect = (w - col_w, 0, w, h)
            seam_x = w - col_w
            text_box = (w - col_w + round(margin * 0.7), top_pad, w - margin, h - bot_pad)
        glass = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glass)
        gd.rectangle(col_rect, fill=(*pal["paper"], 224))
        gd.line((seam_x, 0, seam_x, h), fill=(*pal["accent"], 230), width=max(2, round(unit * 0.0028)))
        scene = Image.alpha_composite(fitted.convert("RGBA"), glass).convert("RGB")
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        tw_col = text_box[2] - text_box[0]
        if clean_brand:
            _typeset_block(draw, ts, (text_box[0], top_pad, text_box[2], top_pad + round(h * 0.12)), [("brand", clean_brand, "body", 0.027, 0.0)], pal, recipe, unit, v_align="top", align_override="left")
        mid_blocks = standard_blocks(tw_col, 0.086 if not wide else 0.090, include_brand=False, include_sub=True, include_cta=False, sub_ratio=0.030)
        _typeset_block(draw, ts, (text_box[0], top_pad + round(h * 0.14), text_box[2], h - bot_pad - round(h * 0.18)), mid_blocks, pal, recipe, unit, v_align="center", align_override="left")
        bot_y = h - bot_pad - round(h * 0.16)
        if price_tag and not protected_subject:
            badge_box = _draw_price_badge(draw, ts, price_tag, pal, unit, text_box[0], bot_y, align="left", scale=0.86)
            cta_y0 = badge_box[3] + round(unit * 0.016)
        else:
            cta_y0 = bot_y
        if footer:
            _typeset_block(draw, ts, (text_box[0], cta_y0, text_box[2], h - bot_pad), [("cta", footer, "body", 0.027, 0.0)], pal, recipe, unit, v_align="top", align_override="left")

    elif arch == "floating_card":
        fitted, box = _fit_photo(photo, (w, h), protect_full=False)
        scene = fitted
        card_pad = round(unit * 0.042)
        eff_anchor = anchor if wide else _quiet_vertical_anchor(fitted)
        if wide:
            cw = round(w * 0.45)
            cx0 = margin if eff_anchor == "left" else w - margin - cw
            card_rect = (cx0, margin, cx0 + cw, h - margin)
        elif eff_anchor == "top":
            card_rect = (margin, top_pad, w - margin, round(h * 0.42))
        else:
            card_rect = (margin, round(h * 0.57), w - margin, h - bot_pad)
        card_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card_layer)
        rad = round(unit * 0.022)
        cd.rounded_rectangle(card_rect, radius=rad, fill=(*pal["paper"], 244))
        border_col = (*pal["accent"], 130) if recipe["ornament"] == "hairline_rule" else (*pal["ink"], 36)
        cd.rounded_rectangle(card_rect, radius=rad, outline=border_col, width=max(1, round(unit * 0.002)))
        scene = Image.alpha_composite(scene.convert("RGBA"), card_layer).convert("RGB")
        text_box = (card_rect[0] + card_pad, card_rect[1] + card_pad, card_rect[2] - card_pad, card_rect[3] - card_pad)
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        _typeset_block(draw, ts, text_box, standard_blocks(text_box[2] - text_box[0], 0.092), pal, recipe, unit)
        if price_tag and not protected_subject and not wide:
            py_badge = top_pad if eff_anchor == "bottom" else (h - bot_pad - round(unit * 0.072))
            _draw_price_badge(draw, ts, price_tag, pal, unit, w - margin, py_badge, align="right")

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
                text_box = (g_pad, p_rect[3] + round(g_pad * 0.72), w - g_pad, h - bot_pad)
        fitted, rel = _fit_photo(photo, (p_rect[2] - p_rect[0], p_rect[3] - p_rect[1]), protect_full=protected_subject, backdrop_color=pal["paper"])
        scene.paste(fitted, p_rect[:2])
        box = (p_rect[0] + rel[0], p_rect[1] + rel[1], p_rect[0] + rel[2], p_rect[1] + rel[3])
        frame_pad = round(unit * 0.01)
        sd.rectangle((p_rect[0] - frame_pad, p_rect[1] - frame_pad, p_rect[2] + frame_pad, p_rect[3] + frame_pad), outline=hair_col, width=hair_w)
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        _typeset_block(draw, ts, text_box, standard_blocks(text_box[2] - text_box[0], 0.094), pal, recipe, unit)
        if price_tag and not protected_subject and anchor == "bottom" and not wide:
            _draw_price_badge(draw, ts, price_tag, pal, unit, p_rect[2] - round(unit * 0.025), p_rect[1] + round(unit * 0.025), align="right")

    elif arch == "ledger":
        # Artlook-inspired Swiss Editorial Ledger: asymmetric upper photo + crisp horizontal ledger rules + structured bottom columns
        if wide:
            pw = round(w * 0.50)
            p_rect = (w - pw, 0, w, round(h * 0.72)) if anchor == "left" else (0, 0, pw, round(h * 0.72))
            t_x0, t_x1 = (margin, w - pw - margin) if anchor == "left" else (pw + margin, w - margin)
            title_box = (t_x0, margin, t_x1, round(h * 0.70))
            foot_y0 = round(h * 0.75)
        else:
            p_h = round(h * 0.50)
            p_w = round(w * 0.62)
            p_rect = (w - p_w, top_pad, w - margin, top_pad + p_h) if anchor == "left" else (margin, top_pad, margin + p_w, top_pad + p_h)
            # Left/right editorial masthead column next to photo
            meta_x0, meta_x1 = (margin, p_rect[0] - round(margin * 0.55)) if anchor == "left" else (p_rect[2] + round(margin * 0.55), w - margin)
            sd.rectangle((meta_x0, top_pad, meta_x1, top_pad + p_h), fill=pal["zone_tint"])
            title_box = (margin, p_rect[3] + round(margin * 0.55), w - margin, round(h * 0.83))
            foot_y0 = round(h * 0.855)
        fitted, rel = _fit_photo(photo, (p_rect[2] - p_rect[0], p_rect[3] - p_rect[1]), protect_full=protected_subject, backdrop_color=pal["paper"])
        scene.paste(fitted, p_rect[:2])
        box = (p_rect[0] + rel[0], p_rect[1] + rel[1], p_rect[0] + rel[2], p_rect[1] + rel[3])
        # Crisp Swiss ledger rules
        sd.line((margin, foot_y0 - round(unit * 0.014), w - margin, foot_y0 - round(unit * 0.014)), fill=pal["accent"], width=max(2, round(unit * 0.0026)))
        if not wide:
            sd.line((margin, p_rect[3] + round(margin * 0.28), w - margin, p_rect[3] + round(margin * 0.28)), fill=hair_col, width=hair_w)
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        if not wide:
            # Put brand + serial index cleanly inside the Swiss side ledger box
            meta_blocks = []
            if clean_brand:
                meta_blocks.append(("brand", clean_brand, "body", 0.028, 0.0))
            meta_blocks.append(("cta", recipe["serial"], "numeric", 0.024, 0.016))
            _typeset_block(draw, ts, (meta_x0 + round(unit * 0.02), top_pad + round(unit * 0.025), meta_x1 - round(unit * 0.02), top_pad + p_h - round(unit * 0.025)), meta_blocks, pal, recipe, unit, v_align="top", align_override="left")
        # Main title & subtitle in the spacious mid ledger band
        mid_blocks = standard_blocks(title_box[2] - title_box[0], 0.098, include_brand=wide, include_sub=True, include_cta=False)
        _typeset_block(draw, ts, title_box, mid_blocks, pal, recipe, unit, v_align="center", align_override="left")
        # Bottom ledger strip: CTA on left, crisp price anchor on right
        foot_h = h - bot_pad - foot_y0
        if price_tag:
            _draw_price_badge(draw, ts, price_tag, pal, unit, w - margin, foot_y0 + max(0, (foot_h - round(unit * 0.068)) // 2), align="right", scale=0.92)
            cta_x1 = w - margin - round(unit * 0.34)
        else:
            cta_x1 = w - margin
        if footer:
            _typeset_block(draw, ts, (margin, foot_y0, max(margin + 80, cta_x1), h - bot_pad), [("cta", footer, "body", 0.030, 0.0)], pal, recipe, unit, v_align="center", align_override="left")

    elif arch == "offset":
        # Artlook-inspired Asymmetric Offset: vertical chromatic structural band + offset photo + opposite-aligned typography
        band_w = round(w * 0.30)
        band_x0 = round(w * 0.56) if anchor == "right" else round(w * 0.14)
        sd.rectangle((band_x0, 0, band_x0 + band_w, h), fill=pal["zone_tint"])
        if wide:
            p_w = round(w * 0.52)
            p_h = round(h * 0.72)
            p_rect = (margin, margin, margin + p_w, margin + p_h) if anchor == "right" else (w - margin - p_w, margin, w - margin, margin + p_h)
            text_box = (p_rect[2] + margin, margin, w - margin, h - margin) if anchor == "right" else (margin, margin, p_rect[0] - margin, h - margin)
        else:
            p_w = round(w * 0.76)
            p_h = round(h * 0.50)
            p_rect = (margin, top_pad, margin + p_w, top_pad + p_h) if anchor == "right" else (w - margin - p_w, top_pad, w - margin, top_pad + p_h)
            text_box = (margin, p_rect[3] + round(margin * 0.65), w - margin, h - bot_pad)
        fitted, rel = _fit_photo(photo, (p_rect[2] - p_rect[0], p_rect[3] - p_rect[1]), protect_full=protected_subject, backdrop_color=pal["paper"])
        scene.paste(fitted, p_rect[:2])
        box = (p_rect[0] + rel[0], p_rect[1] + rel[1], p_rect[0] + rel[2], p_rect[1] + rel[3])
        # Subtle inner editorial keyline inside photo (Artlook signature detail!)
        inset = max(8, round(unit * 0.015))
        sd.rectangle((p_rect[0] + inset, p_rect[1] + inset, p_rect[2] - inset, p_rect[3] - inset), outline=(255, 252, 246), width=max(1, round(unit * 0.0018)))
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        _typeset_block(draw, ts, text_box, standard_blocks(text_box[2] - text_box[0], 0.095), pal, recipe, unit)
        if price_tag and not wide:
            px_anchor = w - margin if anchor == "right" else margin
            _draw_price_badge(draw, ts, price_tag, pal, unit, px_anchor, top_pad + round(unit * 0.02), align="right" if anchor == "right" else "left", scale=0.90)

    elif arch == "monument":
        # Artlook-inspired Centered Monument: bold centered masthead headline at top + framed gallery photo + centered commercial colophon
        if wide:
            p_w = round(w * 0.48)
            p_rect = ((w - p_w) // 2, margin, (w + p_w) // 2, h - margin)
            left_box = (margin, margin, p_rect[0] - margin, h - margin)
            right_box = (p_rect[2] + margin, margin, w - margin, h - margin)
            fitted, rel = _fit_photo(photo, (p_rect[2] - p_rect[0], p_rect[3] - p_rect[1]), protect_full=protected_subject, backdrop_color=pal["paper"])
            scene.paste(fitted, p_rect[:2])
            box = (p_rect[0] + rel[0], p_rect[1] + rel[1], p_rect[0] + rel[2], p_rect[1] + rel[3])
            if image_layers is not None:
                image_layers.append(("stage", scene.copy(), (0, 0)))
            _typeset_block(draw, ts, left_box, standard_blocks(left_box[2] - left_box[0], 0.088, include_sub=False, include_cta=False), pal, recipe, unit, align_override="left")
            _typeset_block(draw, ts, right_box, standard_blocks(right_box[2] - right_box[0], 0.088, include_brand=False, include_sub=True, include_cta=True)[1:], pal, recipe, unit, align_override="left")
        else:
            head_y1 = round(h * 0.30)
            foot_y0 = round(h * 0.82)
            p_margin = round(w * 0.11)
            p_rect = (p_margin, head_y1 + round(unit * 0.028), w - p_margin, foot_y0 - round(unit * 0.028))
            fitted, rel = _fit_photo(photo, (p_rect[2] - p_rect[0], p_rect[3] - p_rect[1]), protect_full=protected_subject, backdrop_color=pal["paper"])
            scene.paste(fitted, p_rect[:2])
            box = (p_rect[0] + rel[0], p_rect[1] + rel[1], p_rect[0] + rel[2], p_rect[1] + rel[3])
            sd.line((p_margin, head_y1 + round(unit * 0.010), w - p_margin, head_y1 + round(unit * 0.010)), fill=hair_col, width=hair_w)
            sd.line((p_margin, foot_y0 - round(unit * 0.010), w - p_margin, foot_y0 - round(unit * 0.010)), fill=hair_col, width=hair_w)
            if image_layers is not None:
                image_layers.append(("stage", scene.copy(), (0, 0)))
            head_blocks = standard_blocks(w - 2 * margin, 0.096, include_brand=True, include_sub=False, include_cta=False)
            _typeset_block(draw, ts, (margin, top_pad, w - margin, head_y1), head_blocks, pal, recipe, unit, align_override="center")
            foot_blocks = []
            if subtitle:
                foot_blocks.append(("sub", subtitle, "body", 0.036, 0.0))
            if footer and footer != subtitle:
                foot_blocks.append(("cta", footer, "body", 0.029, 0.014))
            if foot_blocks:
                _typeset_block(draw, ts, (margin, foot_y0, w - margin, h - bot_pad), foot_blocks, pal, recipe, unit, align_override="center")

    elif arch == "ribbon":
        # Artlook-inspired Panoramic Cinema Ribbon: edge-to-edge full-width photo band between top masthead & bottom commercial strip
        if wide:
            band_y0, band_y1 = round(h * 0.30), round(h * 0.74)
        else:
            band_y0, band_y1 = round(h * 0.31), round(h * 0.74)
        p_rect = (0, band_y0, w, band_y1)
        fitted, rel = _fit_photo(photo, (w, band_y1 - band_y0), protect_full=protected_subject, backdrop_color=pal["paper"])
        scene.paste(fitted, (0, band_y0))
        box = (rel[0], band_y0 + rel[1], rel[2], band_y0 + rel[3])
        sd.line((0, band_y0, w, band_y0), fill=pal["accent"], width=max(2, round(unit * 0.0028)))
        sd.line((0, band_y1, w, band_y1), fill=pal["accent"], width=max(2, round(unit * 0.0028)))
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        top_blocks = standard_blocks(w - 2 * margin, 0.096, include_brand=True, include_sub=False, include_cta=False)
        _typeset_block(draw, ts, (margin, top_pad, w - margin, band_y0 - round(unit * 0.022)), top_blocks, pal, recipe, unit, align_override="center")
        bot_y0 = band_y1 + round(unit * 0.026)
        bot_blocks = []
        if display_subtitle:
            bot_blocks.append(("sub", display_subtitle, "body", 0.035, 0.0))
        if footer and footer != display_subtitle:
            bot_blocks.append(("cta", footer, "body", 0.029, 0.014))
        if price_tag and not wide:
            _draw_price_badge(draw, ts, price_tag, pal, unit, w - margin, bot_y0 + max(0, (h - bot_pad - bot_y0 - round(unit * 0.068)) // 2), align="right", scale=0.92)
            text_x1 = w - margin - round(unit * 0.35)
            if bot_blocks:
                _typeset_block(draw, ts, (margin, bot_y0, max(margin + 120, text_x1), h - bot_pad), bot_blocks, pal, recipe, unit, align_override="left")
        elif bot_blocks:
            _typeset_block(draw, ts, (margin, bot_y0, w - margin, h - bot_pad), bot_blocks, pal, recipe, unit, align_override="center")

    elif arch == "edge":
        # Artlook-inspired Side-Bleed Edge Composition: full-height edge photo + opposing tall editorial column
        pw = round(w * (0.56 if wide else 0.54))
        if anchor == "left":
            p_rect = (w - pw, 0, w, h)
            text_box = (margin, top_pad, w - pw - round(margin * 0.85), h - bot_pad)
            seam_x = p_rect[0]
        else:
            p_rect = (0, 0, pw, h)
            text_box = (pw + round(margin * 0.85), top_pad, w - margin, h - bot_pad)
            seam_x = p_rect[2]
        fitted, rel = _fit_photo(photo, (p_rect[2] - p_rect[0], p_rect[3] - p_rect[1]), protect_full=protected_subject, backdrop_color=pal["paper"])
        scene.paste(fitted, p_rect[:2])
        box = (p_rect[0] + rel[0], p_rect[1] + rel[1], p_rect[0] + rel[2], p_rect[1] + rel[3])
        sd.line((seam_x, 0, seam_x, h), fill=pal["accent"], width=max(2, round(unit * 0.003)))
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        col_w = text_box[2] - text_box[0]
        # Top brand tag
        if clean_brand:
            _typeset_block(draw, ts, (text_box[0], top_pad, text_box[2], top_pad + round(h * 0.12)), [("brand", clean_brand, "body", 0.027, 0.0)], pal, recipe, unit, v_align="top", align_override="left")
        # Mid oversized headline + subtitle
        mid_blocks = standard_blocks(col_w, 0.088 if not wide else 0.095, include_brand=False, include_sub=True, include_cta=False, sub_ratio=0.030)
        _typeset_block(draw, ts, (text_box[0], top_pad + round(h * 0.14), text_box[2], h - bot_pad - round(h * 0.18)), mid_blocks, pal, recipe, unit, v_align="center", align_override="left")
        # Bottom anchored price + CTA
        bot_y = h - bot_pad - round(h * 0.16)
        if price_tag:
            badge_box = _draw_price_badge(draw, ts, price_tag, pal, unit, text_box[0], bot_y, align="left", scale=0.86)
            cta_y0 = badge_box[3] + round(unit * 0.016)
        else:
            cta_y0 = bot_y
        if footer:
            _typeset_block(draw, ts, (text_box[0], cta_y0, text_box[2], h - bot_pad), [("cta", footer, "body", 0.027, 0.0)], pal, recipe, unit, v_align="top", align_override="left")

    elif arch == "window":
        # Artlook-inspired Architectural Arch Aperture: rounded-arch photo window over deep/porcelain architectural field
        if wide:
            p_w = round(w * 0.46)
            p_rect = (w - margin - p_w, margin, w - margin, h - margin) if anchor == "left" else (margin, margin, margin + p_w, h - margin)
            text_box = (margin, margin, p_rect[0] - margin, h - margin) if anchor == "left" else (p_rect[2] + margin, margin, w - margin, h - margin)
        else:
            p_pad_x = round(w * 0.10)
            p_rect = (p_pad_x, top_pad + round(unit * 0.02), w - p_pad_x, round(h * 0.62))
            text_box = (margin, p_rect[3] + round(margin * 0.58), w - margin, h - bot_pad)
        fitted, rel = _fit_photo(photo, (p_rect[2] - p_rect[0], p_rect[3] - p_rect[1]), protect_full=protected_subject, backdrop_color=pal["paper"])
        arch_r = round((p_rect[2] - p_rect[0]) * 0.42) if not protected_subject else 0
        if arch_r > 12:
            _paste_arch_window(scene, fitted, p_rect, arch_r)
            # Subtle concentric outer architectural arch keyline
            kp = round(unit * 0.014)
            kx0, ky0, kx1, ky1 = p_rect[0] - kp, p_rect[1] - kp, p_rect[2] + kp, p_rect[3]
            kr = min(arch_r + kp, (kx1 - kx0) // 2)
            sd.arc((kx0, ky0, kx0 + kr * 2, ky0 + kr * 2), 180, 270, fill=hair_col, width=hair_w)
            sd.arc((kx1 - kr * 2, ky0, kx1, ky0 + kr * 2), 270, 360, fill=hair_col, width=hair_w)
            sd.line((kx0 + kr, ky0, kx1 - kr, ky0), fill=hair_col, width=hair_w)
            sd.line((kx0, ky0 + kr, kx0, ky1), fill=hair_col, width=hair_w)
            sd.line((kx1, ky0 + kr, kx1, ky1), fill=hair_col, width=hair_w)
        else:
            scene.paste(fitted, p_rect[:2])
        box = (p_rect[0] + rel[0], p_rect[1] + rel[1], p_rect[0] + rel[2], p_rect[1] + rel[3])
        # Subtle architectural base line under the arch
        sd.line((p_rect[0] - round(unit * 0.02), p_rect[3] + round(unit * 0.012), p_rect[2] + round(unit * 0.02), p_rect[3] + round(unit * 0.012)), fill=pal["accent"], width=max(2, round(unit * 0.0024)))
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        _typeset_block(draw, ts, text_box, standard_blocks(text_box[2] - text_box[0], 0.094), pal, recipe, unit, align_override="left")
        if price_tag and not wide:
            _draw_price_badge(draw, ts, price_tag, pal, unit, w - margin, text_box[1] + round(unit * 0.006), align="right", scale=0.88)

    elif arch == "diagonal_bleed":
        # Artlook-inspired Diagonal Bleed: upper-right hero photo bleed + elevated opaque lower-left editorial card
        sd.rectangle((0, round(h * 0.45), round(w * 0.42), h), fill=pal["zone_tint"])
        if wide:
            p_rect = (round(w * 0.34), 0, w, round(h * 0.78))
            card_rect = (margin, round(h * 0.24), round(w * 0.48), h - margin)
        else:
            p_rect = (round(w * 0.16), 0, w, round(h * 0.62))
            card_rect = (margin, round(h * 0.55), round(w * 0.86), h - bot_pad)
        fitted, rel = _fit_photo(photo, (p_rect[2] - p_rect[0], p_rect[3] - p_rect[1]), protect_full=protected_subject, backdrop_color=pal["paper"])
        scene.paste(fitted, p_rect[:2])
        box = (p_rect[0] + rel[0], p_rect[1] + rel[1], p_rect[0] + rel[2], p_rect[1] + rel[3])
        # Solid opaque editorial card with razor-sharp accent left border (zero text/photo muddiness)
        sd.rectangle(card_rect, fill=pal["paper"])
        sd.rectangle(card_rect, outline=hair_col, width=hair_w)
        bar_w = max(5, round(unit * 0.009))
        sd.rectangle((card_rect[0], card_rect[1], card_rect[0] + bar_w, card_rect[3]), fill=pal["accent"])
        pad = round(unit * 0.036)
        text_box = (card_rect[0] + bar_w + pad, card_rect[1] + pad, card_rect[2] - pad, card_rect[3] - pad)
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        _typeset_block(draw, ts, text_box, standard_blocks(text_box[2] - text_box[0], 0.090), pal, recipe, unit, align_override="left")
        if price_tag and not wide:
            _draw_price_badge(draw, ts, price_tag, pal, unit, w - margin, top_pad, align="right", scale=0.90)

    elif arch == "diptych_focus":
        # Trupic Exclusive Lookbook Diptych: hero product frame + zoomed macro texture detail panel + calm editorial zone
        gutter = max(8, round(unit * 0.016))
        if wide:
            p_h = h - 2 * margin
            main_w = round((w - 2 * margin) * 0.42)
            det_w = round((w - 2 * margin) * 0.16)
            p_rect = (margin, margin, margin + main_w, margin + p_h)
            d_rect = (p_rect[2] + gutter, margin, p_rect[2] + gutter + det_w, margin + p_h)
            text_box = (d_rect[2] + margin, margin, w - margin, h - margin)
        else:
            p_h = round((h - top_pad - bot_pad) * 0.56)
            inner_w = w - 2 * margin - gutter
            main_w = round(inner_w * 0.66)
            det_w = inner_w - main_w
            p_rect = (margin, top_pad, margin + main_w, top_pad + p_h)
            d_rect = (p_rect[2] + gutter, top_pad, w - margin, top_pad + p_h)
            text_box = (margin, p_rect[3] + round(margin * 0.65), w - margin, h - bot_pad)
        fitted, rel = _fit_photo(photo, (p_rect[2] - p_rect[0], p_rect[3] - p_rect[1]), protect_full=protected_subject, backdrop_color=pal["paper"])
        scene.paste(fitted, p_rect[:2])
        box = (p_rect[0] + rel[0], p_rect[1] + rel[1], p_rect[0] + rel[2], p_rect[1] + rel[3])
        detail_img = _crop_macro_detail(photo, (d_rect[2] - d_rect[0], d_rect[3] - d_rect[1]))
        scene.paste(detail_img, d_rect[:2])
        sd.line((margin, p_rect[3] + round(margin * 0.30), w - margin, p_rect[3] + round(margin * 0.30)), fill=hair_col, width=hair_w)
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        _typeset_block(draw, ts, text_box, standard_blocks(text_box[2] - text_box[0], 0.094), pal, recipe, unit, align_override="left")
        if price_tag and not wide:
            _draw_price_badge(draw, ts, price_tag, pal, unit, w - margin, text_box[1] + round(unit * 0.004), align="right", scale=0.88)

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
                text_box = (margin, top_pad, w - margin, h - ph - round(margin * 0.65))
            else:
                p_rect = (0, 0, w, ph)
                text_box = (margin, ph + round(margin * 0.72), w - margin, h - bot_pad)
        fitted, rel = _fit_photo(photo, (p_rect[2] - p_rect[0], p_rect[3] - p_rect[1]), protect_full=protected_subject, backdrop_color=pal["paper"])
        scene.paste(fitted, p_rect[:2])
        box = (p_rect[0] + rel[0], p_rect[1] + rel[1], p_rect[0] + rel[2], p_rect[1] + rel[3])
        if wide:
            seam_x = p_rect[0] if anchor == "left" else p_rect[2]
            sd.line((seam_x, 0, seam_x, h), fill=pal["accent"], width=max(2, round(unit * 0.003)))
        else:
            seam_y = p_rect[1] if anchor == "top" else p_rect[3]
            sd.line((0, seam_y, w, seam_y), fill=pal["accent"], width=max(2, round(unit * 0.003)))
        if image_layers is not None:
            image_layers.append(("stage", scene.copy(), (0, 0)))
        _typeset_block(draw, ts, text_box, standard_blocks(text_box[2] - text_box[0], 0.096), pal, recipe, unit)

    # Subtle Artlook-style corner registration ticks (only on light/dark paper layouts where clean)
    if recipe["ornament"] == "corner_ticks" and arch not in FULL_BLEED_ARCHITECTURES and arch != "ribbon":
        tick = round(unit * 0.020)
        tc = (*pal["accent"], 175)
        lw = max(2, round(unit * 0.0022))
        m_t = round(unit * 0.028)
        draw.line((m_t, m_t, m_t + tick, m_t), fill=tc, width=lw)
        draw.line((m_t, m_t, m_t, m_t + tick), fill=tc, width=lw)
        draw.line((w - m_t - tick, h - m_t, w - m_t, h - m_t), fill=tc, width=lw)
        draw.line((w - m_t, h - m_t - tick, w - m_t, h - m_t), fill=tc, width=lw)

    recipe["titleContrast"] = pal["titleContrast"]
    recipe["bodyContrast"] = pal["bodyContrast"]
    return scene, layer, box, recipe
