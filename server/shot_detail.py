"""Select one visible feature and its location in the full merchant photograph."""

import math
import re

import numpy as np
from PIL import Image


def textured_patch(photo, bounds, min_contrast=0):
    """Locate a patch entirely inside the subject, in full-image pixels."""
    subject = photo.crop(bounds)
    proxy = np.asarray(subject.resize((64, 64)).convert("RGBA"))
    choices = []
    for y in range(4, 44, 4):
        for x in range(4, 44, 4):
            patch = proxy[y:y + 20, x:x + 20]
            if patch[:, :, 3].min() >= 245:
                choices.append((patch[:, :, :3].std(axis=(0, 1)).mean(), x, y))
    if not choices:
        return None
    contrast, x, y = max(choices)
    if contrast < min_contrast:
        return None
    rect = tuple(bounds[i % 2] + round(v * subject.size[i % 2] / 64)
                 for i, v in enumerate((x, y, x + 20, y + 20)))
    return rect if rect[0] < rect[2] and rect[1] < rect[3] else None


def normalized_box(box):
    return (
        isinstance(box, list) and len(box) == 4
        and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in box)
        and box[0] < box[2] and box[1] < box[3]
    )


def visible_phrase(label):
    if not isinstance(label, str):
        return ""
    label = label.strip()
    # This field describes the pictured feature. Commercial terms belong in the approved copy.
    if not 1 <= len(label) <= 20 or re.search(
        r"[\n。！？；%％]|销量|续航|小时|折扣|保修|防水|抗菌|治愈|零风险|第一名|全网第一|全市第一|\d\s*(?:元|折)", label
    ):
        return ""
    return label


def detail_from_input(value, source):
    if not isinstance(value, dict) or not normalized_box(value.get("region")):
        return None
    label = visible_phrase(value.get("label"))
    if not label:
        return None
    return dict(label=label, region=value["region"], source=source)


def resolvable(region, size):
    l, t, r, b = region
    return min((r - l) * size[0], (b - t) * size[1]) >= 12


def merchant_detail(request, path):
    if request.get("visualDetail") is None:
        return None
    detail = detail_from_input(request["visualDetail"], "商家框选")
    if not path or not detail or request.get("assetConfirmed") is not True:
        raise ValueError("请框选原图细节，填写 20 字以内的可见特征，并确认素材。")
    with Image.open(path) as photo:
        if not resolvable(detail["region"], photo.size):
            raise ValueError("细节选区过小，请框住原图上完整可辨的一处特征。")
    return detail


def surface_detail(asset):
    with Image.open(asset) as opened:
        photo = opened.convert("RGBA")
        photo.thumbnail((384, 384), Image.Resampling.LANCZOS)
    if photo.getchannel("A").getextrema()[0] == 255:
        # Only infer a foreground on a plain studio backdrop. Borders of a
        # lifestyle photograph cannot establish which textured object is the SKU.
        rgb = np.asarray(photo, dtype=float)[:, :, :3]
        border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]))
        background = np.median(border, axis=0)
        if np.percentile(np.abs(border - background).max(axis=1), 95) > 8:
            return None
        foreground = np.abs(rgb - background).max(axis=2) > 32
        if not 0.05 < foreground.mean() < 0.9:
            return None
        photo.putalpha(Image.fromarray(foreground))
    bounds = photo.getchannel("A").getbbox()
    if not bounds:
        return None
    patch = textured_patch(photo, bounds, min_contrast=12)
    box = patch or bounds
    region = [v / photo.size[i % 2] for i, v in enumerate(box)]
    return dict(label="表面纹理" if patch else "商品轮廓", claim="近看表面纹理" if patch else "看清商品轮廓",
                region=region, source="商品原图")


def product_detail(plan, asset=None):
    if marked := plan.get("markedDetail"):
        return marked
    if observed := plan.get("sourceReview", {}).get("visualDetail"):
        return observed
    if region := plan.get("identityRegion"):
        return dict(label="商品标识", claim="认准这处标识", region=region, source="标识选区")
    if asset and (surface := surface_detail(asset)):
        return surface
    if asset or plan.get("visualSource") in ("cutout", "photograph"):
        return dict(label="商品实拍", region=[0, 0, 1, 1], source="完整原图")
    return None
