"""Compose the photographic plate and exact typography as separate film layers."""

import re
from pathlib import Path
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageOps, ImageStat
import numpy as np

from .posters import SCENES, backdrop, extend_edges, luminance
from .design import DIRECTIONS
from .poster_composition import LAYOUTS, boxes as reference_boxes, picture_layout
from .shot_detail import textured_patch
from .photo_grid import grid_layout
from .campaign import poster_footer


def video_stage(image):
    # Keep moving footage readable beneath stationary light captions, without
    # altering the separately composited original product pixels.
    return Image.blend(image.convert('RGB'), Image.new('RGB',image.size,'#0d0c0d'),0.78)


def material_plate(photo, bounds, size):
    """Find a textured, opaque patch inside the subject rather than magnifying its backdrop."""
    rect = textured_patch(photo, bounds)
    if not rect:
        return None
    detail = photo.crop(rect).convert("RGB")
    stage = ImageOps.fit(detail, size, Image.Resampling.BICUBIC)
    # Lift the colours at the text edge while keeping the far end of the macro legible.
    paper = Image.blend(detail.resize((1, 1)), Image.new("RGB", (1, 1), "#fffae8"), 0.82)
    yy, xx = np.mgrid[0:1:160j, 0:1:160j]
    fade = Image.fromarray(np.uint8(230 * np.clip(1 - xx * 0.95 - yy * 0.55, 0, 1) ** 1.4))
    fade = fade.resize(size, Image.Resampling.BILINEAR)
    return Image.composite(paper.resize(size), stage, fade)


def print_plate(photo, size, palette, layers=None):
    """Separate the tonal roles of a photographic detail into screened inks."""
    w, h = size
    paper = Image.new("RGB", size, palette["paper"])
    if layers is not None:
        layers.append(("paper", paper.copy(), (0, 0)))
    # An observed detail in the upper-right becomes a printed counterpoint to the exact product.
    aw, ah = photo.size
    detail = photo.crop(
        (round(aw * 0.34), round(ah * 0.29), round(aw * 0.81), round(ah * 0.79))
    )
    dw, dh = round(w * 0.62), round(h * 0.34)
    grey = (
        np.asarray(ImageOps.fit(detail.convert("L"), (dw, dh)), dtype=np.float32) / 255
    )
    yy, xx = np.ogrid[:dh, :dw]
    pitch = max(3, min(size) * 0.006)
    screen = (
        np.cos((xx * 0.93 + yy * 0.37) * 2 * np.pi / pitch)
        + np.cos((yy * 0.93 - xx * 0.37) * 2 * np.pi / pitch)
    ) / 4 + 0.5
    coverage = np.clip((1 - grey - screen) * 6 + 0.45, 0, 1)
    origin = (w - dw, round(h * 0.29))

    def apply_ink(name, color, coverage_mask):
        ink_layer = Image.new("RGBA", (dw, dh), color)
        ink_layer.putalpha(coverage_mask)
        paper.paste(ink_layer, origin, coverage_mask)
        if layers is not None:
            layers.append((name, ink_layer, origin))

    if palette["ink"] != palette["accent"]:
        warm = np.asarray(ImageOps.fit(detail.convert("RGB"), (dw, dh)), dtype=float)
        second = np.clip((warm[:, :, 0] - warm[:, :, 2]) / 96, 0, 1)
        ink = Image.fromarray(
            np.uint8(255 * np.clip((second - screen) * 5 + 0.4, 0, 1))
        )
        apply_ink("accent-ink", palette["accent"], ink)
    mask = Image.fromarray(np.uint8(225 * coverage))
    apply_ink("primary-ink", palette["ink"], mask)
    return paper


def photograph(plan, asset, background, size, index, image_layers, repair, ts, detail=None, photo_area=None):
    w, h = size
    wide = w > h
    if index == 2 and not detail and plan.get("identityRegion"):
        detail = {"region": plan["identityRegion"]}
    art = plan.get("posterArt", {})
    if plan.get("videoBackground"):
        art = {k:v for k,v in art.items() if k not in ("print","composition","story")}
    treatment = art.get("composition")
    if not index and treatment in LAYOUTS:
        source = asset or background
        if not source and (name := plan.get("scenePhoto")):
            source = SCENES / (name + ".webp")
        photo = None
        if source:
            with Image.open(source) as opened:
                photo = opened.convert("RGBA" if "A" in opened.getbands() else "RGB")
        return picture_layout(
            treatment, size, photo, art.get("lighting"), image_layers, photo_area, repair,
            reference_color=next((r["color"] for r in plan.get("references",[]) if r["role"]=="color"),None),
            framed=plan.get("design", {}).get("photoLayout", "framed") == "framed" if treatment == "photo-grid" else None,
            background=background if asset and treatment == "photo-grid" and not repair else None,
        )
    if not asset:
        sector = DIRECTIONS.get(plan.get("sector"), DIRECTIONS["general"])
        stage = backdrop(plan, None, size, "product", 0, index, background, sector)
        return (
            print_plate(stage, size, art["print"]) if art.get("print") else stage
        ), None
    with Image.open(asset) as opened:
        photo = (
            opened.convert("RGBA")
            if "A" in opened.getbands()
            else opened.convert("RGB")
        )
    alpha = photo.getchannel("A") if photo.mode == "RGBA" else None
    cut = alpha is not None and alpha.getextrema()[0] < 240
    aw, ah = photo.size
    bounds = alpha.getbbox() if cut else (0, 0, aw, ah)
    if not bounds:
        bounds = (0, 0, aw, ah)
    l, t, r, b = bounds
    factor = (1, 1.12, 1.85, 0.91, 1.32, 1.06, 1.55, 0.96)[index]
    max_w, max_h = (0.56 * w, 0.80 * h) if wide else (0.91 * w, 0.49 * h)
    if art.get("print") and not wide:
        max_w, max_h = 0.54 * w, 0.36 * h
    if art.get("story") and not wide:
        max_w, max_h = 0.70 * w, 0.49 * h
    projection = cut and art.get("composition") == "projection"
    ingredient = cut and art.get("composition") == "ingredient"
    material = cut and art.get("composition") == "material"
    if material and not wide:
        max_w, max_h = w * 0.63, h * 0.62
    if ingredient and not wide:
        max_w, max_h = w * 0.58, h * 0.58
    if projection and not wide:
        max_w, max_h = w * 0.63, h * 0.44
    if repair:
        # Leave additional clearance around the mark and copy when rebuilding the composition.
        factor = min(factor, 1.48) * 0.94
    scale = min(max_w / (r - l), max_h / (b - t)) * factor
    if detail:
        region = detail["region"]
        mark = plan.get("identityRegion") or region
        left, top = min(region[0], mark[0]), min(region[1], mark[1])
        right, bottom = max(region[2], mark[2]), max(region[3], mark[3])
        # Leave room for both the selected feature and the identity mark throughout the push.
        safe_x = (0.54 * w, 0.91 * w) if wide else (0.11 * w, 0.89 * w)
        safe_y = (0.15 * h, 0.84 * h) if wide else (0.33 * h, 0.79 * h)
        feature_fit = min((safe_x[1] - safe_x[0]) / ((region[2] - region[0]) * aw),
                          (safe_y[1] - safe_y[0]) / ((region[3] - region[1]) * ah))
        # Let the feature occupy the picture area, while bounding upsampling of small details.
        scale = max(scale, min(feature_fit * 0.86, scale * 2.4))
        scale = min(scale, (safe_x[1] - safe_x[0]) / ((right - left) * aw),
                    (safe_y[1] - safe_y[0]) / ((bottom - top) * ah))
    pw, ph = max(1, round(aw * scale)), max(1, round(ah * scale))
    cx, cy = (0.70, 0.51) if wide else (0.51, 0.57)
    if art.get("print") and not wide:
        cx, cy = 0.32, 0.65
    if art.get("story") and not wide:
        cx, cy = 0.41, 0.61
    if projection and not wide:
        cx, cy = (0.645, 0.49) if index != 2 else (0.54, 0.49)
    if ingredient and not wide:
        cx, cy = 0.62, 0.49
    if material and not wide:
        cx, cy = (0.73 if index == 2 else 0.64), 0.55
    fx, fy = (l + r) / (2 * aw), (t + b) / (2 * ah)
    if detail:
        fx, fy = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2
        cx, cy = (0.73 if wide else 0.5), 0.55
    x, y = round(cx * w - fx * pw), round(cy * h - fy * ph)
    if detail:
        x = round(max(safe_x[0] - left * pw, min(x, safe_x[1] - right * pw)))
        y = round(max(safe_y[0] - top * ph, min(y, safe_y[1] - bottom * ph)))
    box = (x, y, x + pw, y + ph)
    visible = (max(x, 0), max(y, 0), min(w, x + pw), min(h, y + ph))
    if detail:
        # Sample only on-screen pixels. A macro of a small object in a large PNG
        # must not allocate its enlarged, mostly off-screen transparent margins.
        sample = tuple((v - (x, y)[i % 2]) * (aw, ah)[i % 2] / (pw, ph)[i % 2]
                       for i, v in enumerate(visible))
        placed = photo.resize((visible[2] - visible[0], visible[3] - visible[1]),
                              Image.Resampling.LANCZOS, box=sample)
        position = visible[:2]
    else:
        placed = photo.resize((pw, ph), Image.Resampling.LANCZOS)
        position = (x, y)
    if not cut and not art.get("print") and not background:
        # Preserve a continuous photographic setting beyond the edges of the source.
        cropped = placed if detail else placed.crop(tuple(v - position[i % 2] for i, v in enumerate(visible)))
        return extend_edges(cropped.convert("RGB"), size, visible), box
    path = background or (SCENES / "optics-light.webp" if art.get("optics") else None)
    if projection and not background:
        path = SCENES / "optics-projection.webp"
    if art.get("orchard") and not background:
        path = SCENES / "orchard-ip.webp"
    macro = material_plate(photo, bounds, size) if material else None
    if macro is not None:
        scene = macro
    elif ingredient and not background:
        tone = np.asarray(photo.convert("RGB").resize((48, 48)), dtype=float)
        visible = np.asarray(alpha.resize((48, 48))) > 220
        pixels = tone[visible] if visible.any() else tone.reshape(-1, 3)
        pigment = np.percentile(pixels, 55, axis=0)
        ink_color = tuple(int(v) for v in np.clip(pigment * 0.38, 14, 92))
        paper = tuple(int(v) for v in (np.array([248, 239, 220]) * 0.9 + pigment * 0.1))
        rng = np.random.default_rng(71)
        grain = rng.normal(0, 2, (360, 270, 1))
        scene = Image.fromarray(
            np.uint8(np.clip(np.array(paper) + grain, 0, 255))
        ).resize(size, Image.Resampling.BILINEAR)
    elif art.get("print"):
        scene = print_plate(photo, size, art["print"], image_layers)
    elif path:
        with Image.open(path) as plate:
            scene = ImageOps.fit(plate.convert("RGB"), size, Image.Resampling.LANCZOS)
            if plan.get("videoBackground"):
                scene = video_stage(scene)
    else:
        # A tonal studio sweep derived from the subject, with light at upper left.
        sampled = photo.resize((80, 80))
        avg = ImageStat.Stat(sampled.convert("RGB"), sampled.getchannel("A")).mean
        dark = tuple(round(v * 0.17) for v in avg)
        light = tuple(round(min(255, v * 0.54 + 55)) for v in avg)
        wash = Image.linear_gradient("L").rotate(28, expand=True)
        scene = ImageOps.colorize(ImageOps.fit(wash, size), dark, light)
    if (projection or ingredient) and not index and art.get("modelMark"):
        from .typography import Typesetter

        mark = Image.new("RGBA", size)
        writing = Typesetter(ts.custom)
        writing.editable_text = []
        rect = (round(0.24 * w), round(0.055 * h), round(0.988 * w), round(0.38 * h))
        if wide:
            rect = (round(0.51 * w), round(0.03 * h), round(0.98 * w), round(0.42 * h))
        word, role, color, align = art["modelMark"], "display", "#452A21", "right"
        if ingredient:
            word = "\n".join(word) if not wide else word
            rect = (round(0.045 * w), round(0.06 * h), round(0.79 * w), round(0.74 * h))
            role, color, align = (
                "serif",
                "#%02x%02x%02x" % (ink_color if not background else (49, 61, 30)),
                "left",
            )
        writing.draw(
            ImageDraw.Draw(mark), word, rect, min(size) * 0.55, role, color, align=align
        )
        ts.used.update(writing.used)
        mark.info["editable_runs"] = writing.editable_text
        if image_layers is not None:
            image_layers.extend(
                [
                    ("background", scene.copy(), (0, 0)),
                    ("model-lettering", mark, (0, 0)),
                ]
            )
        scene.paste(mark, mask=mark.getchannel("A"))
    shadow = Image.new("L", (max(2, w // 4), max(2, h // 4)))
    ground = y + b * ph / ah
    sx = x + (l + r) * pw / (2 * aw)
    sw = (r - l) * pw / aw * 0.51
    sy = max(5, 0.022 * h)
    ImageDraw.Draw(shadow).ellipse(
        ((sx - sw) / 4, (ground - sy) / 4, (sx + sw) / 4, (ground + sy) / 4), fill=160
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, w * 0.006))).resize(size)
    if image_layers is not None:
        if not image_layers:
            image_layers.append(("background", scene.copy(), (0, 0)))
        contact = Image.new("RGBA", size, (6, 5, 6))
        contact.putalpha(shadow)
        image_layers.extend([("shadow", contact, (0, 0)), ("subject", placed, position)])
    scene.paste((6, 5, 6), (0, 0, w, h), shadow)
    scene.paste(placed, position, placed.getchannel("A") if cut else None)
    return scene, box


def campaign_frame(
    plan,
    copy,
    shot,
    size,
    asset,
    background,
    ts,
    index,
    image_layers=None,
    repair=False,
    variant=0,
):
    w, h = size
    wide = w > h
    min_edge = min(size)
    art = plan.get("posterArt", {})
    if plan.get("videoBackground"):
        art = {k:v for k,v in art.items() if k not in ("print","composition","story")}
    treatment = art.get("composition") if not shot else None
    reference_layout = LAYOUTS.get(treatment)
    photo_area = entries = None
    kit = plan.get("brandKit", {})
    from .skill_render import brand_logo
    logo_path = brand_logo(asset, kit) if not shot and plan.get("kind") == "poster" else None
    motif = copy.get("motif")
    if (treatment == "photo-grid" and motif in ("columns", "reply") and asset and not logo_path
            and plan.get("design", {}).get("photoLayout") == motif and w <= h):
        from .moment_poster import conversation
        return conversation(copy, asset, size, ts, image_layers, background, repair)
    if (treatment == "photo-grid" and plan.get("design", {}).get("photoLayout") in ("time", "clock-object", "object")
            and asset and asset.name == "subject.png" and not logo_path):
        from .moment_poster import compose
        return compose(plan, copy, asset, size, background, ts, image_layers)
    if treatment == "photo-grid":
        design = plan.get("design", {})
        mode = design.get("photoLayout", "framed")
        first = design.get("readingOrder", {}).get("first", "offer" if mode == "bleed" and copy.get("offer") else "title")
        brand = kit.get("name") or plan["profile"].get("name", "")
        # Use the infinite parametric editorial layout engine for clean commercial posters
        # (eliminates muddy blurred edge-stretching while preserving protected product fidelity).
        hero_path = asset or background or (SCENES / (plan["scenePhoto"] + ".webp") if plan.get("scenePhoto") else None)
        use_editorial = (
            not shot
            and not plan.get("bundleRole")
            and "moment" not in plan
            and not plan.get("references")
            and not (asset and asset.name == "subject.png")
            and hero_path is not None
            and Path(hero_path).is_file()
        )
        if use_editorial:
            from .layout_engine import compose_editorial_poster
            with Image.open(hero_path) as hero_src:
                hero_img = hero_src.convert("RGB")
            seed_text = f"{copy.get('title','')}|{plan.get('original','')}|{w}x{h}|v{variant}|m{mode}"
            scene, layer, box, recipe = compose_editorial_poster(
                size,
                hero_img,
                ts,
                brand,
                copy,
                seed_text=seed_text,
                logo_path=logo_path,
                protected_subject=bool(asset),
                repair=repair,
                image_layers=image_layers,
                kit=kit,
            )
            plan["editorialLayout"] = recipe
            return scene, layer, box
        # The note belongs in the caption. Leave the merchant's photograph room on the card.
        grid_copy = {**copy, "body": copy.get("posterDeck", "")} if "moment" in plan else copy
        photo_area, entries = grid_layout(
            size, ts, brand, grid_copy, "" if "moment" in plan else art.get("detail"), mode, first,
            body=copy.get("body") if plan.get("bundleRole") else "",
            logo=bool(logo_path), has_picture=bool(asset or background or plan.get("scenePhoto")),
        )
    scene, box = photograph(
        plan, asset, background, size, index, image_layers, repair, ts,
        (shot or {}).get("evidence") if index == 2 else None, photo_area,
    )
    layer = Image.new("RGBA", size)
    draw = ImageDraw.Draw(layer)
    # Preserve exact source pixels; add contrast to the surrounding stage only.
    mask = Image.new("L", (1, 256))
    mask.putdata(
        [
            round(191 * max((1 - y / 100) if y < 100 else 0, (y - 180) / 75, 0))
            for y in range(256)
        ]
    )
    if wide:
        mask = mask.transpose(Image.Transpose.ROTATE_90)
    shade = mask.resize(size, Image.Resampling.BILINEAR)
    if plan.get("videoBackground") or reference_layout or art.get("print") or art.get("story") or (asset and asset.name == "subject.png"):
        shade = Image.new("L", size, 0)
    elif box:
        ImageDraw.Draw(shade).rectangle(box, fill=0)
    scene = Image.composite(Image.new("RGB", size, (13, 12, 13)), scene, shade)
    if image_layers is not None and not image_layers:
        image_layers.append(("photograph", scene, (0, 0)))
    if plan.get("lettering") in ("both", "han", "latin") and index in (0, 1):
        from .lettering import apply_lettering

        protected = Image.new("L", size, 0)
        if box:
            ImageDraw.Draw(protected).rectangle(box, fill=255)
        sector = DIRECTIONS.get(plan.get("sector"), DIRECTIONS["general"])
        if palette := art.get("print"):
            sector = {**sector, "ink": palette["ink"], "paper": palette["paper"]}
        marked = apply_lettering(
            scene,
            plan,
            ts,
            sector,
            plan.get("design", {}).get("id", "product"),
            protected,
            margin=bool(asset),
        )
        if image_layers is not None:
            difference = ImageChops.difference(scene, marked)
            bounds = difference.getbbox()
            if bounds:
                patch = marked.crop(bounds).convert("RGBA")
                channels = difference.crop(bounds).split()
                patch.putalpha(
                    ImageChops.lighter(
                        ImageChops.lighter(channels[0], channels[1]), channels[2]
                    ).point(lambda v: 255 if v else 0)
                )
                image_layers.append(("letterforms", patch, bounds[:2]))
        scene = marked

    def place_logo(area):
        with Image.open(logo_path) as source:
            logo = ImageOps.contain(source.convert("RGBA"), (area[2] - area[0], area[3] - area[1]))
        scene.paste(logo, area[:2], logo)
        if image_layers is not None:
            image_layers.append(("brand-logo", logo, area[:2]))

    if entries is not None:
        for value, role, points, area in entries:
            if role == "logo":
                place_logo(area)
                continue
            tone = scene.crop(area).resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
            ink = "#181417" if luminance(tone) > 0.22 else "#fffaf1"
            if kit.get("color") and role in ("display", "numeric"):
                brand_luma = luminance(ImageColor.getrgb(kit["color"]))
                light = luminance(tone)
                if (max(light, brand_luma) + 0.05) / (min(light, brand_luma) + 0.05) >= 4.5:
                    ink = kit["color"]
            ts.draw(draw, value, area, points, role, ink)
        return scene, layer, box
    if wide:
        brand = (0.05, 0.085, 0.43, 0.15)
        headline = (0.05, 0.19, 0.45, 0.60)
        support = (0.05, 0.65, 0.43, 0.80)
        foot = (0.05, 0.82, 0.45, 0.94)
    else:
        brand = (0.055, 0.045, 0.945, 0.089)
        headline = (0.05, 0.095, 0.96, 0.285)
        support = (0.055, 0.825, 0.945, 0.905)
        foot = (0.055, 0.915, 0.945, 0.975)
    projected = bool(
        asset and asset.name == "subject.png" and art.get("composition") == "projection"
    )
    food_type = bool(
        asset and asset.name == "subject.png" and art.get("composition") == "ingredient"
    )
    if food_type and not wide:
        brand = (0.58, 0.035, 0.95, 0.080)
        headline = (0.052, 0.75, 0.95, 0.88)
        support = (0.055, 0.885, 0.95, 0.937)
        foot = (0.055, 0.939, 0.95, 0.985)
    if projected and not wide:
        brand = (0.055, 0.035, 0.52, 0.075)
        headline = (0.045, 0.69, 0.95, 0.855)
        support = (0.055, 0.865, 0.94, 0.915)
        foot = (0.055, 0.92, 0.945, 0.973)
    if art.get("story") and not wide:
        headline = (0.055, 0.10, 0.62, 0.29)
    material_title = art.get("composition") == "material" and not wide and not shot
    upright = material_title and re.fullmatch(r"[\u3400-\u9fff]{2,7}", copy["title"]) and not re.search("横排|横向排字", plan["original"])
    if material_title:
        headline = (0.065, 0.10, 0.23, 0.70) if upright else (0.052, 0.096, 0.94, 0.215)
    if art.get("print") and not wide:
        headline = (0.055, 0.11, 0.89, 0.28)
        support = (0.055, 0.32, 0.36, 0.48)
    if index == 2 and not wide and not projected:
        headline = (0.055, 0.10, 0.945, 0.235)
    if shot and art.get("composition") == "material" and not wide:
        # The camera moves on the product plane; keep the stationary title outside its sweep.
        headline = (0.05, 0.09, 0.35, 0.32) if index == 2 else (0.05, 0.095, 0.74, 0.17)
    if index == 2 and shot and shot.get("evidence") and not wide:
        headline = (0.055, 0.10, 0.945, 0.235)
    if reference_layout:
        _, brand, headline, support, foot = reference_boxes(treatment, size)

    def line(text, rect, points, role):
        if not text:
            return
        area = tuple(round(v * size[i % 2]) for i, v in enumerate(rect))

        def ink(bounds):
            if plan.get("videoBackground"):
                return "#fff8ee"
            region = scene.crop(bounds).resize((1, 1), Image.Resampling.BOX)
            if palette := art.get("print"):
                return palette["ink"]
            return "#191519" if luminance(region.getpixel((0, 0))) > 0.27 else "#fff8ee"

        ts.draw(draw, text, area, min_edge * points / 1080, role, ink)

    if logo_path:
        left, top, right, bottom = brand
        edge = round(h * (bottom - top))
        pos = round(w * left), round(h * top)
        place_logo((*pos, pos[0] + edge, pos[1] + edge))
        brand = (left + (edge + min_edge * 0.016) / w, top, right, bottom)
    brand_name = kit.get("name") or plan["profile"].get("name", "")
    if not shot or (index == 3 and shot.get("line") != brand_name):
        line(brand_name, brand, 36, "body")
    role = "serif" if (plan.get("design") or {}).get("id") == "editorial" else "display"
    if projected:
        role = "serif"
    if shot:
        line(shot["line"], headline, 155 if index != 2 else 110, role)
        line(shot.get("caption"), foot, 39, "body")
    else:
        title = "\n".join(copy["title"]) if upright else copy["title"]
        points = reference_layout["points"] if reference_layout else 225
        title_role = "serif" if material_title else role
        if reference_layout:
            title_role = reference_layout["role"]
            if re.fullmatch(r".{3,14}[，。！？：].{3,16}", title) and ts.width(
                title, round(min_edge * points / 1080), title_role
            ) > w * (headline[2] - headline[0]):
                title = re.sub(r"([，。！？：])", r"\1\n", title, count=1)
        line(title, headline, points, title_role)
        # Full copy is included in copy.txt. The key visual carries its factual support.
        if copy.get("writingSkill", {}).get("posterHeadings"):
            line(copy.get("posterDeck", copy["body"]), support, 48, "body")
            line(poster_footer(copy, copy.get("offer"), copy.get("terms")), foot, 36, "body")
        else:
            support_text = (
                copy.get("offer")
                or art.get("detail")
                or ("" if food_type or art.get("composition") == "material" else re.split(r"[。！？]", copy.get("body", ""))[0])
            )
            if plan.get("bundleRole") and plan.get("kind") == "poster":
                support_text = copy.get("body") or support_text
                if copy.get("offer") and copy["offer"] not in support_text:
                    support_text = copy["offer"] + "  " + support_text
            if copy.get("terms") and copy["terms"] not in support_text:
                support_text += "  " + copy["terms"]
            line(support_text, support, 44, "body")
            line(copy.get("cta"), foot, 42, "display")
    return scene, layer, box


def camera_window(size, shot, tick, pace="steady"):
    """Move the lens over the photographic layer; editorial type stays on screen."""
    w, h = size
    # Anchor the detail before the push, and hold the end frame for the name or offer.
    if shot == 2:
        t = max(0, tick - 10) / 61
    elif shot == 3:
        t = min(tick, 53) / 53
    else:
        t = tick / 71
    ease = t * t * (3 - 2 * t)
    if shot == 1:
        zoom, ax, ay = 1.20 - 0.17 * ease, 0.28 + 0.20 * ease, 0.56
    elif shot == 2:
        zoom, ax, ay = 1.04 + 0.12 * ease, 0.73 if w > h else 0.50, 0.55
    elif shot >= 4:
        strength = (0.10, 0.05, 0.14, 0.065)[shot - 4]
        zoom, ax, ay = 1 + strength * (1 - ease), 0.30 + 0.4 * ease, 0.50
    else:
        zoom, ax, ay = 1.055 - 0.055 * ease, 0.55, 0.58
    travel = {"quiet": 0.55, "brisk": 1.22}.get(pace, 1.0)
    zoom = 1 + (zoom - 1) * travel
    cw, ch = round(w / zoom), round(h / zoom)
    x, y = round((w - cw) * ax), round((h - ch) * ay)
    return x, y, x + cw, y + ch


def film_planes(layers, size):
    """Place the subject and contact shadow in front of the photographic set."""
    if not layers or layers[0][0] != "background":
        return None
    near = Image.new("RGBA", size)
    for _, image, xy in layers[1:]:
        near.alpha_composite(image.convert("RGBA"), dest=xy)
    return layers[0][1], near


def moving_frame(plate, foreground, index, tick, pace="steady"):
    dims = plate.size
    window = camera_window(dims, index, tick, pace)
    if foreground is None:
        return plate.crop(window).resize(dims, Image.Resampling.BILINEAR)
    # During a dolly the distant set travels less than the product nearest the lens.
    far = tuple(
        round(v + (target - v) * 0.45) for v, target in zip((0, 0, *dims), window)
    )
    frame = plate.crop(far).resize(dims, Image.Resampling.BILINEAR)
    subject = foreground.crop(window).resize(dims, Image.Resampling.BILINEAR)
    frame.paste(subject, mask=subject.getchannel("A"))
    return frame
