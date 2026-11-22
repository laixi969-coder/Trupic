"""Generate only concept scenery. Product masks are composited from the original upload."""

import base64
import io
import json
import re
import time
import urllib.request

from PIL import Image, ImageOps

from .model import reserve_provider_call, route
from .store import db, now
from .design import DIRECTIONS
from . import qwen_image


def make_scene(folder, plan, asset, kind, fresh, strict=False):
    art_direction = plan.get("posterArt", {})
    if kind != "copy" and art_direction.get("print"):
        return None, "实拍照片孔版分色"
    if asset and asset.name == "subject.png" and art_direction.get("composition") == "material":
        return None, "商品原片纹理取景"
    selected = route("image")
    cfg = dict(imageUrl=selected["url"], imageModel=selected["model"], imageKey=selected["key"])
    if kind == "copy" or not (cfg["imageUrl"] and cfg["imageModel"]):
        return None, "本地排版"
    if asset and asset.name != "subject.png" and not plan.get("autoCreation"):
        return None, "原图排版"
    # A revision reuses the same approved scene. No extra provider billing.
    path = folder.parent / "concept.webp"
    if path.exists():
        return path, cfg["imageModel"]
    if not fresh:
        return None, "本地排版"
    prompt = (
        "为商家营销设计摄影背景，全幅商业摄影、清楚的主光方向、视觉集中、无文字、无商标。仅作概念配图，"
        "不要虚构门店的陈设、产品包装、优惠或品牌。"
    )
    if asset and art_direction.get("story"):
        prompt += f"依据动作「{art_direction['story']}」设计角色所处环境，在角色视线方向绘制相应道具。角色所在位置留空，角色及其配件随后从原稿合成。"
    elif asset:
        prompt += "按本次创作指令建立环境与道具。为原图主体留出位置，光照方向和接触面应与主体相容。"
    else:
        prompt += "用生活氛围与构图表达主题，避免具体品牌与可识别商铺。"
    prompt += f"主题：{plan['subject']}。营销目的：{plan['goal']}。创意方法：{plan['angle']}。镜头：{plan['shot']}。"
    design = plan.get("design")
    optimized = plan.get("promptBrief", {}).get("prompts", {}).get("image")
    if design and not optimized:
        prompt += (
            " 版式所需取景：" + design["scene"] + "。所有实际文字由排版引擎另行置入。"
        )
    art = DIRECTIONS.get(plan.get("sector"), DIRECTIONS["general"])
    out = plan.get("output", {})
    width, height = out.get("width", 1024), out.get("height", 1024)
    colors = re.findall(
        r"#[0-9a-fA-F]{6}|(?:墨绿|森林绿|抹茶绿|奶油白|酒红|绛红|靛蓝|陶土色|柠檬黄|雾紫|冷蓝|暖白|珊瑚橙|[红橙黄绿青蓝紫黑白灰粉金银棕]色)",
        plan.get("original", ""),
    )
    palette = "、".join(dict.fromkeys(colors)) or "、".join(
        art[k] for k in ("ink", "paper", "accent")
    )
    if not optimized:
        prompt += f" 行业镜头：{art['shot']} {art['focus']}。"
    prompt += f"场景用色参考 {palette}。目标画布 {width}×{height}，全幅连续摄影。"
    if asset:
        prompt += "仅制作空背景，商品由商家照片合成。"
    elif width > height:
        prompt += "商品在右半幅，左半幅的光线应平稳，供标题及小字落版。"
    else:
        prompt += "保护下半幅商品轮廓，上方和侧边保留平稳的文字留白。"
    if optimized:
        prompt += " 本次创作指令：" + optimized
    payload = {
        "model": cfg["imageModel"],
        "prompt": prompt,
        "size": "1536x1024"
        if width > height
        else "1024x1536"
        if height > width
        else "1024x1024",
        "n": 1,
        "response_format": "b64_json",
    }
    headers = {"Content-Type": "application/json"}
    if cfg["imageKey"]:
        headers["Authorization"] = "Bearer " + cfg["imageKey"]
    started, ok = time.monotonic(), False
    try:
        if cfg["imageModel"] in qwen_image.MODELS:
            data = qwen_image.generate(cfg, prompt, payload["size"])
        else:
            req = urllib.request.Request(
                cfg["imageUrl"], json.dumps(payload).encode(), headers
            )
            reserve_provider_call("image")
            with urllib.request.urlopen(req, timeout=95) as response:
                raw = response.read(23_000_001)
            if len(raw) > 23_000_000:
                raise ValueError("图像响应过大")
            data = base64.b64decode(json.loads(raw)["data"][0]["b64_json"], validate=True)
        with Image.open(io.BytesIO(data)) as img:
            if min(img.size) < 320 or img.width * img.height > 24_000_000:
                raise ValueError("图像尺寸不适用")
            folder.parent.mkdir(parents=True, exist_ok=True)
            cleaned = ImageOps.exif_transpose(img).convert("RGB")
            temp = path.with_suffix(".tmp")
            cleaned.save(temp, format="WEBP", quality=91)
            temp.replace(path)
        ok = True
        return path, cfg["imageModel"]
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        if strict:
            raise ValueError("图片生成接口未返回可用画面，请检查图片连接后重试此项。") from exc
        return None, "本地排版（图像服务未返回可用画面）"
    finally:
        with db(True) as c:
            c.execute('INSERT INTO model_call(day,kind,platform,model,ok,ms) VALUES(?,?,?,?,?,?)',(now()[:10],'image',selected.get('provider','default'),cfg['imageModel'],ok,round((time.monotonic()-started)*1000)))
