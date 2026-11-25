"""Apply a quoted edit to a poster background, keeping the rest of the export intact."""

import base64
import io
import json
import secrets
import time
import urllib.request
import xml.etree.ElementTree as ET

from PIL import Image, ImageChops, ImageEnhance

from . import model
from .shot_detail import normalized_box
from .store import db, now
from .video_api import NoRedirect

LOCAL = {"提亮": 1.2, "压暗": 0.8}


def validate(box, instruction, protected=()):
    if (
        not normalized_box(box)
        or not isinstance(instruction, str)
        or not 1 <= len(instruction.strip()) <= 400
    ):
        raise ValueError("请框选背景，并填写局部修改要求。")
    if any(
        box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1]
        for b in protected
    ):
        raise ValueError("选区覆盖了文字或商品，请缩小背景选区。")
    if instruction not in LOCAL and not model.route("edit")["model"]:
        raise ValueError("本地可用提亮或压暗。其他修改需要先配置图片编辑模型。")


def request_edit(cfg, image, instruction, fields, timeout):
    """Send the supplied pixels to a configured Images Edits endpoint."""
    raw = io.BytesIO()
    image.save(raw, "PNG")
    boundary = "trupic-" + secrets.token_hex(16)
    parts = []
    for key, value in (
        ("model", cfg["model"]),
        ("prompt", instruction),
        *fields.items(),
    ):
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        )
    parts += [
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="patch.png"\r\nContent-Type: image/png\r\n\r\n'.encode(),
        raw.getvalue(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    headers = {"Content-Type": "multipart/form-data; boundary=" + boundary, "User-Agent": "Trupic/1.0"}
    if cfg.get("key"):
        headers["Authorization"] = "Bearer " + cfg["key"]
    request = urllib.request.Request(cfg["url"], b"".join(parts), headers)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        payload = response.read(23_000_001)
    if len(payload) > 23_000_000:
        raise ValueError("修图响应过大。")
    return base64.b64decode(json.loads(payload)["data"][0]["b64_json"], validate=True)


def cloud_patch(cfg, image, instruction):
    # Send only the selected patch. A provider can never modify the surrounding pixels.
    model.reserve_provider_call("edit")
    started, ok, reason = time.monotonic(), False, None
    try:
        raw = request_edit(cfg, image, instruction, {"response_format": "b64_json"}, 95)
        with Image.open(io.BytesIO(raw)) as edited:
            if min(edited.size) < 8 or edited.width * edited.height > 24_000_000:
                raise ValueError("修图尺寸不适用。")
            patch = edited.convert("RGB").resize(image.size, Image.Resampling.LANCZOS)
        if not ImageChops.difference(image, patch).getbbox():
            raise ValueError("修图服务未修改选区。")
        ok = True
        return patch
    except Exception as exc:
        reason = model.failure_reason(exc)
        raise
    finally:
        with db(True) as c:
            c.execute(
                "INSERT INTO model_call(day,kind,platform,model,ok,ms,job,error) VALUES(?,?,?,?,?,?,current_model_job(),?)",
                (
                    now()[:10],
                    "edit",
                    cfg["provider"],
                    cfg["model"],
                    ok,
                    round((time.monotonic() - started) * 1000),
                    reason,
                ),
            )


def protected(frame):
    boxes = [sample[0] for sample in frame["text"]]
    if frame.get("product"):
        boxes.append(frame["product"])
    return [[v / frame["size"][i % 2] for i, v in enumerate(box)] for box in boxes]


def apply(folder, works, layout, spec, job):
    plan = spec["plan"]
    frame = layout["frames"][0]
    patches = plan.get("backgroundPatches", [])
    pending = spec.get("regionEdit")
    if not patches and not pending:
        return
    target = folder / "poster.png"
    source_folder = (
        works / pending["work"] / str(pending["version"]) if pending else folder
    )
    with Image.open(source_folder / "poster.png") as source:
        canvas = source.convert("RGB")
    svg = source_folder / "poster.svg"
    tree = ET.parse(svg) if svg.exists() else None
    if pending:
        # The source raster already contains prior patches.
        ops = [pending]
    else:
        ops = patches
    for op in ops:
        box = op["box"]
        pixels = tuple(round(v * canvas.size[i % 2]) for i, v in enumerate(box))
        if min(pixels[2] - pixels[0], pixels[3] - pixels[1]) < 8:
            raise ValueError("背景选区太小。")
        if any(
            box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1]
            for b in protected(frame)
        ):
            raise ValueError("修改会遮挡当前版式的商品或文字，请调整选区。")
        if pending:
            path = folder / (job + ".png")
            if not path.exists():
                before = canvas.crop(pixels)
                text = op["instruction"]
                if text in LOCAL:
                    patch = ImageEnhance.Brightness(before).enhance(LOCAL[text])
                else:
                    cfg = model.route("edit")
                    if not cfg["model"]:
                        raise ValueError("图片编辑连接不可用，请检查后重试。")
                    try:
                        patch = cloud_patch(cfg, before, text)
                    except OSError:
                        if not cfg.get("backup"):
                            raise
                        patch = cloud_patch(cfg["backup"], before, text)
                if not ImageChops.difference(before, patch).getbbox():
                    raise ValueError("所选区域没有可见变化，请更换选区或调整要求。")
                temp = path.with_suffix(".tmp")
                patch.save(temp, "PNG")
                temp.replace(path)
        else:
            path = works / op["work"] / str(op["version"]) / (op["job"] + ".png")
        with Image.open(path) as patch:
            canvas.paste(
                patch.resize((pixels[2] - pixels[0], pixels[3] - pixels[1])), pixels[:2]
            )
        if tree is not None:
            ET.SubElement(
                tree.getroot(),
                "{http://www.w3.org/2000/svg}image",
                {
                    "x": str(pixels[0]),
                    "y": str(pixels[1]),
                    "width": str(pixels[2] - pixels[0]),
                    "height": str(pixels[3] - pixels[1]),
                    "{http://www.w3.org/1999/xlink}href": "data:image/png;base64,"
                    + base64.b64encode(path.read_bytes()).decode(),
                },
            )
    if tree is not None:
        tree.write(folder / "poster.svg", encoding="utf-8", xml_declaration=True)
    else:
        (folder / "poster.svg").unlink(missing_ok=True)
    dpi = plan["output"]["dpi"]
    canvas.save(target, dpi=(dpi, dpi))
    frame["preview"] = canvas.resize((160, 160))


def save_layout(folder, layout):
    """Keep the glyph masks used at delivery so a local edit can recheck the exact same layout."""
    import zipfile

    frame = layout["frames"][0]
    data = {k: frame[k] for k in ("size", "product", "subjectBounds") if k in frame}
    data.update(fonts=layout["fonts"], fallback=layout["fallback"], text=[])
    with zipfile.ZipFile(
        folder / "poster-layout.zip", "w", zipfile.ZIP_DEFLATED
    ) as package:
        for i, (box, mask, size, text) in enumerate(frame["text"]):
            buf = io.BytesIO()
            mask.save(buf, "PNG")
            package.writestr(f"{i}.png", buf.getvalue())
            data["text"].append([box, size, text])
        package.writestr("layout.json", json.dumps(data, ensure_ascii=False))


def original_layout(source, dest, copy):
    import zipfile

    archive = source / "poster-layout.zip"
    if not archive.is_file():
        return None
    with zipfile.ZipFile(archive) as package:
        data = json.loads(package.read("layout.json"))
        samples = []
        for i, (box, size, text) in enumerate(data["text"]):
            with Image.open(io.BytesIO(package.read(f"{i}.png"))) as im:
                samples.append((tuple(box), im.copy(), size, text))
    with Image.open(source / "poster.png") as im:
        preview = im.convert("RGB").resize((160, 160))
    frame = dict(
        text=samples,
        size=tuple(data["size"]),
        product=data.get("product"),
        subjectBounds=data.get("subjectBounds"),
        movement=0,
        preview=preview,
    )
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "copy.txt").write_text(
        "\n\n".join(copy[k] for k in ("title", "body", "cta") if copy[k]),
        encoding="utf-8",
    )
    return dict(frames=[frame], fonts=data["fonts"], fallback=data["fallback"])
