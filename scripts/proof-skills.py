"""Render all nine local workflows with one fictional product; no model calls.

Run: .venv/bin/python scripts/proof-skills.py --out .trupic/skill-proof/final
The isolated database, source illustrations, gallery and downloads stay in --out.
"""

import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import zipfile
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
OUT = args.out.resolve()
OUT.mkdir(parents=True, exist_ok=True)
os.environ["TRUPIC_DATA"] = str(OUT / "workspace")
os.environ["TRUPIC_CUTOUT"] = "/missing-proof-do-not-use-network"
from server import app as studio
from server.skill_catalog import SKILLS
from server.typography import Typesetter, SANS


def sources():
    """Explicitly illustrated fixtures, never presented as product photography."""
    folder = OUT / "sources"
    folder.mkdir(exist_ok=True)
    ts = Typesetter()
    for view in ("front", "side", "back"):
        im = Image.new("RGBA", (1000, 1000))
        d = ImageDraw.Draw(im)
        # A cylindrical tea tin with a consistent lid, body and three label views.
        for x in range(235, 765):
            light = 0.78 + 0.22 * (1 - abs(x - 420) / 530)
            d.line(
                (x, 245, x, 800),
                fill=tuple(int(v * light) for v in (224, 229, 204)),
                width=1,
            )
        d.ellipse((235, 740, 765, 850), fill="#c4ccb3")
        d.rectangle((235, 630, 765, 790), fill="#d4ddc2")
        d.ellipse((235, 190, 765, 300), fill="#284e3a", outline="#102e20", width=5)
        d.arc((250, 200, 750, 290), 180, 355, fill="#739178", width=5)
        d.rectangle((235, 282, 765, 310), fill="#254b36")
        if view == "front":
            ts.draw(
                d, "春山", (290, 345, 710, 440), 82, "serif", "#244c36", align="center"
            )
            ts.draw(
                d, "抹茶粉", (290, 465, 710, 545), 64, "sans", "#244c36", align="center"
            )
            ts.draw(
                d,
                "MATCHA",
                (290, 560, 710, 615),
                39,
                "display",
                "#244c36",
                align="center",
            )
            d.line((330, 650, 670, 650), fill="#466447", width=2)
            ts.draw(
                d,
                "净含量 100g",
                (300, 685, 700, 735),
                31,
                "sans",
                "#244c36",
                align="center",
            )
        elif view == "side":
            d.line((570, 320, 570, 790), fill="#98aa88", width=4)
            ts.draw(d, "春山", (300, 360, 540, 435), 55, "serif", "#244c36")
            ts.draw(d, "抹茶粉\n100g / 罐", (310, 500, 550, 640), 32, "sans", "#244c36")
            for i in range(9):
                d.line((610, 430 + i * 23, 710, 430 + i * 23), fill="#708466", width=3)
        else:
            ts.draw(d, "春山 · 抹茶粉", (290, 350, 710, 415), 38, "sans", "#244c36")
            ts.draw(
                d,
                "演示包装\n净含量 100g\n搭配牛奶冲调",
                (290, 445, 710, 600),
                29,
                "sans",
                "#244c36",
            )
            for i in range(42):
                x = 315 + i * 8
                d.rectangle((x, 650, x + (2 if i % 3 else 5), 730), fill="#244c36")
        im.save(folder / f"{view}.png")
    logo = Image.new("RGBA", (600, 360))
    ts.draw(
        ImageDraw.Draw(logo),
        "春山",
        (50, 40, 550, 275),
        180,
        "serif",
        "#244c36",
        align="center",
    )
    ts.draw(
        ImageDraw.Draw(logo),
        "CHUNSHAN",
        (80, 280, 520, 330),
        35,
        "display",
        "#244c36",
        align="center",
    )
    logo.save(folder / "logo.png")
    return folder


client = studio.app.test_client()
client.get("/api/state")
with client.session_transaction() as session:
    tenant = session["tenant"]
with studio.db(True) as c:
    c.execute("UPDATE merchant SET credits=500 WHERE id=?", (tenant,))
    c.execute(
        "INSERT INTO ledger(tenant,delta,note,created)VALUES(?,?,?,?)",
        (tenant, 380, "隔离演示验收额度", studio.now()),
    )


def fixture_options(spec, tenant, previous=()):
    base = {**studio.draft_copy(spec["plan"]), **spec["replacement"]}
    return [base, {**base, "body": "春山抹茶粉，搭配牛奶冲调。"}]


def post(path, **data):
    r = client.post("/api/" + path, json=data)
    if r.status_code != 200:
        raise RuntimeError((path, r.status_code, r.json))
    return r.json


src = sources()
assets = {}
for view in ("front", "side", "back", "logo"):
    with (src / f"{view}.png").open("rb") as f:
        response = client.post(
            "/api/assets", data={"image": (f, f"春山抹茶-演示{view}.png")}
        )
    assert response.status_code == 200, response.json
    assets[view] = response.json["id"]
    print("SOURCE", view, response.json.get("risk"), flush=True)
post("brand-kit", name="春山", logo=assets["logo"], color="#244c36", font="")
post(
    "profile",
    name="春山",
    industry="饮品",
    product="抹茶粉",
    facts="100g罐装，搭配牛奶冲调，48元/罐",
)
records = []
template = None
with patch.object(
    studio.model, "chat_request", side_effect=AssertionError("本地技能不可调用模型 API")
):
    for skill, info in SKILLS.items():
        req = dict(
            skill=skill,
            title="春山抹茶粉",
            benefits="100g罐装 · 搭配牛奶冲调 · 48元/罐",
            terms="11月25日至30日，仅限单罐装，不与其他优惠同享",
            asset=assets["front"],
            sideAsset=assets["side"],
            backAsset=assets["back"],
            assetConfirmed=True,
            ratio="square",
            resolution=1080,
            cta="查看规格，选一罐春山",
            template=template,
        )
        if skill in ("brand", "mockup"):
            req.update(
                asset=assets["logo"],
                title="春山",
                benefits="品牌名称：春山；品牌色：深绿；应用于抹茶粉包装",
            )
        if skill == "live":
            req["benefits"] = "11月25日 19:30开播 · 抹茶牛奶冲调演示 · 100g罐装"
        if skill == "remake":
            req.update(
                title="给牛奶加一点春山",
                benefits="100g罐装抹茶粉 · 搭配牛奶冲调 · 48元/罐",
            )
        quote = post("bundles/preview", **req)
        choice = ""
        if quote["requiresCopyChoice"]:
            with patch("server.copy_choices.write_options", side_effect=fixture_options):
                choice = post("copy-options", quote=quote["quote"])["options"][0]["token"]
        pack = post(
            "bundles",
            copyChoice=choice,
            quote=quote["quote"],
            confirmed=True,
            confirmedCost=quote["cost"],
            requestKey=uuid.uuid4().hex,
        )
        folder = OUT / skill
        folder.mkdir(exist_ok=True)
        for item in pack["items"]:
            until = time.monotonic() + 180
            while True:
                job = client.get("/api/jobs/" + item["job"]).json
                if job["state"] in ("complete", "failed") or time.monotonic() > until:
                    break
                time.sleep(0.2)
            item.update(job=job)
            print(skill, item["role"], job["state"], job.get("error"), flush=True)
        result = client.get("/api/bundles/" + pack["id"]).json
        for item, status in zip(pack["items"], result["items"]):
            item.update(preview=status["preview"], kind=status["kind"])
            if not status["preview"]:
                continue
            response = client.get(status["preview"])
            (folder / f"{item['role']}.png").write_bytes(response.data)
            response.close()
            if status["video"]:
                response = client.get(status["video"])
                target = folder / f"{item['role']}.mp4"
                target.write_bytes(response.data)
                response.close()
                for t in (1, 4, 7):
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-v",
                            "error",
                            "-y",
                            "-ss",
                            str(t),
                            "-i",
                            str(target),
                            "-frames:v",
                            "1",
                            str(folder / f"{item['role']}-{t}s.png"),
                        ],
                        check=True,
                    )
                if skill == "motion":
                    template = item["job"]["work"]
        if result["complete"]:
            response = client.get(result["download"])
            assert response.status_code == 200
            with zipfile.ZipFile(io.BytesIO(response.data)) as z:
                assert not z.testzip()
            (folder / "素材包.zip").write_bytes(response.data)
            response.close()
        records.append(
            dict(
                skill=skill,
                name=info["name"],
                request=req,
                pack=pack,
                complete=result["complete"],
            )
        )
(OUT / "results.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))

# Review thumbnails over a checkerboard so alpha errors are visible.
font = ImageFont.truetype(str(SANS), 20)
tiles = []
for row in records:
    for item in row["pack"]["items"]:
        path = OUT / row["skill"] / f"{item['role']}.png"
        if not path.exists():
            continue
        tiles.append((row["name"] + " / " + item["label"], path))
    if row["skill"] in ("motion", "remake"):
        tiles.extend(
            (row["name"] + f" / {t}s", OUT / row["skill"] / f"{row['skill']}-{t}s.png")
            for t in (1, 4, 7)
        )
sheet = Image.new("RGB", (5 * 340, ((len(tiles) + 4) // 5) * 380), "#e9e7e1")
draw = ImageDraw.Draw(sheet)
for index, (label, path) in enumerate(tiles):
    x, y = index % 5 * 340, index // 5 * 380
    tile = Image.new("RGBA", (320, 320), "white")
    td = ImageDraw.Draw(tile)
    for xx in range(0, 320, 20):
        for yy in range(0, 320, 20):
            if (xx + yy) // 20 % 2:
                td.rectangle((xx, yy, xx + 19, yy + 19), fill="#ddd")
    with Image.open(path) as original:
        im = original.convert("RGBA")
        im.thumbnail((320, 320))
        tile.alpha_composite(im, ((320 - im.width) // 2, (320 - im.height) // 2))
    sheet.paste(tile.convert("RGB"), (x + 10, y + 40))
    draw.text((x + 10, y + 8), label, font=font, fill="#203429")
sheet.save(OUT / "总览.jpg", quality=93)
sections = []
for row in records:
    cards = []
    for item in row["pack"]["items"]:
        p = f"{row['skill']}/{item['role']}"
        media = (
            f'<video controls preload="metadata" poster="{p}.png" src="{p}.mp4"></video>'
            if item["kind"] == "video"
            else f'<a href="{p}.png"><img loading="lazy" src="{p}.png"></a>'
        )
        cards.append(
            f"<figure>{media}<figcaption>{item['label']} · {item['job']['state']}</figcaption></figure>"
        )
    sections.append(
        f'<section><h2>{row["name"]} <a href="{row["skill"]}/素材包.zip" download>下载素材包</a></h2><div>{"".join(cards)}</div></section>'
    )
(OUT / "index.html").write_text(
    """<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>春山抹茶 · 9 类技能实测</title><style>body{margin:0;background:#f4f1e9;color:#203429;font:16px system-ui;padding:4vw}h1{font-size:36px}h2{margin-top:50px}h2 a{font-size:15px;margin-left:20px}a{color:#315744}section>div{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px}figure{margin:0;background:white;padding:12px;border-radius:12px}img,video{width:100%;height:340px;object-fit:contain;background:repeating-conic-gradient(#eee 0% 25%,white 0% 50%) 0/20px 20px}figcaption{padding:16px 0 4px}p{max-width:850px;line-height:1.8}</style><h1>春山抹茶 · 创作技能实测</h1><p>同一款演示商品，9 类流程，25 张图片和 2 条视频。包装三视图为本地绘制的测试插画，商品信息、价格及活动日期均为演示数据。点击图片查看原尺寸；视频可直接播放。</p><p><a href="全部成品.zip" download>下载全部成品 ZIP</a> · <a href="总览.jpg">查看总览</a></p>"""
    + "".join(sections)
)
with zipfile.ZipFile(OUT / "全部成品.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for path in OUT.rglob("*"):
        if (
            path.is_file()
            and "workspace" not in path.relative_to(OUT).parts
            and path.name != "全部成品.zip"
        ):
            archive.write(path, path.relative_to(OUT))
print("GALLERY", OUT / "index.html", flush=True)
assert all(row["complete"] for row in records), (
    "Some deliveries failed; inspect results.json"
)
