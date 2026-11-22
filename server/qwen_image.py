"""Generate a complete poster with Bailian's synchronous Qwen-Image Images API."""

import argparse
import base64
import io
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from .model import reserve_provider_call, settings
from .store import init


MODELS = ("qwen-image-3.0-pro", "qwen-image-3.0")


def generate(cfg, prompt, size, reference=None):
    if cfg["imageModel"] not in MODELS:
        raise ValueError("请选择支持同步 PNG 返回的 Qwen-Image 3.0 模型。")
    if not cfg["imageUrl"] or not cfg["imageKey"]:
        raise ValueError("请在 Trupic 的图像生成设置中填写百炼图像接口与 API Key。")
    if not prompt.strip():
        raise ValueError("整张海报提示词为空。")
    width, height = map(int, size.split("x"))
    if min(width, height) <= 0 or not 512**2 <= width * height <= 2048**2 or max(width, height) > 8 * min(width, height):
        raise ValueError("输出画幅超出百炼的像素或比例范围。")
    payload = dict(model=cfg["imageModel"], prompt=prompt, size=size,
                   n=1, response_format="b64_json", prompt_extend=False)
    if reference is not None:
        with Image.open(reference) as im:
            mime = Image.MIME.get(im.format)
            if mime not in ("image/png", "image/jpeg", "image/webp"):
                raise ValueError("参考图请选择 PNG、JPEG 或 WebP。")
            if max(im.size) > 8000 or max(im.size) > 10 * min(im.size):
                raise ValueError("参考图超过百炼接口支持的尺寸或长宽比。")
        if reference.stat().st_size > 10 * 1024**2:
            raise ValueError("参考图超过百炼接口的 10 MB 上限。")
        encoded = base64.b64encode(reference.read_bytes()).decode("ascii")
        payload["image"] = f"data:{mime};base64,{encoded}"
    request = urllib.request.Request(
        cfg["imageUrl"], json.dumps(payload).encode(),
        {"Authorization": "Bearer " + cfg["imageKey"], "Content-Type": "application/json"},
    )
    reserve_provider_call("image")
    with urllib.request.urlopen(request, timeout=240) as response:
        raw = response.read(32_000_001)
    if len(raw) > 32_000_000:
        raise ValueError("图像响应过大。")
    try:
        data = base64.b64decode(json.loads(raw)["data"][0]["b64_json"], validate=True)
        with Image.open(io.BytesIO(data)) as im:
            if im.format != "PNG" or im.width * im.height > 24_000_000:
                raise ValueError("返回的 PNG 无效。")
            im.verify()
    except (IndexError, KeyError, TypeError, OSError, ValueError) as exc:
        raise ValueError("百炼未返回可用的 PNG。") from exc
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--size", default="1024x1536")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cfg = settings()
    if not cfg["imageUrl"] and not cfg["imageModel"]:
        # A DashScope key is only ever sent to the workspace's official endpoint.
        workspace = os.getenv("DASHSCOPE_WORKSPACE_ID", "")
        if not re.fullmatch(r"[a-zA-Z0-9-]+", workspace):
            parser.exit(2, "请配置 Trupic 的百炼图像服务，或提供北京地域 DASHSCOPE_WORKSPACE_ID 和 DASHSCOPE_API_KEY。\n")
        cfg.update(imageModel=MODELS[0], imageKey=os.getenv("DASHSCOPE_API_KEY", ""),
                   imageUrl=f"https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/images/generations")
    try:
        if args.output.exists():
            raise ValueError("输出文件已存在，请指定新文件名。")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        init()
        result = generate(cfg, args.prompt_file.read_text(), args.size, args.reference)
        with tempfile.NamedTemporaryFile(dir=args.output.parent) as f:
            f.write(result)
            f.flush()
            os.link(f.name, args.output)
    except urllib.error.HTTPError as exc:
        parser.exit(1, f"百炼图像请求失败，HTTP {exc.code}。\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"{cfg['imageModel']}  {args.output}")


if __name__ == "__main__":
    main()
