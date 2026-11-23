"""Use licensed references for color and layout without compositing their pixels."""

from PIL import Image, ImageStat
from .media import photo_layout_features
from .store import DATA


def study(c, tenant, refs, owner):
    if refs is None:
        return []
    if not isinstance(refs, list) or len(refs) > 2:
        raise ValueError("最多可添加一张配色参考和一张构图参考。")
    result = []
    for r in refs:
        if (
            not isinstance(r, dict)
            or r.get("role") not in ("color", "layout")
            or r.get("authorized") is not True
        ):
            raise ValueError("请确认有权使用参考图，并选择参考用途。")
        role = r["role"]
        if any(existing["role"] == role for existing in result):
            raise ValueError("每种参考用途请选择一张图。")
        a = owner(c, "asset", r.get("id"), tenant)
        path = DATA / tenant / "assets" / a["id"] / "original.png"
        if role == "color":
            with Image.open(path) as image:
                image.thumbnail((128, 128))
                swatch = [round(x) for x in ImageStat.Stat(image.convert("RGB")).median]
            result.append(
                dict(
                    id=a["id"],
                    role=role,
                    source=a["name"],
                    authorized=True,
                    color=swatch,
                )
            )
        else:
            features = photo_layout_features(path)
            mode = "bleed" if features.get("calmArea", 0) > 0.45 else "framed"
            result.append(
                dict(
                    id=a["id"],
                    role=role,
                    source=a["name"],
                    authorized=True,
                    layout=mode,
                    features=features,
                )
            )
    return result
