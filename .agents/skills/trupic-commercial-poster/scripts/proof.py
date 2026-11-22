"""Rebuild the gallery with the production compositor; optionally export a proof sheet."""

import argparse
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from server.design import DIRECTIONS, STYLES, choose_style
from server.posters import poster
from server.typography import SANS, Typesetter
from server.campaign_frame import campaign_frame
from server.art_direction import direct
from server.poster_composition import LAYOUTS


def sample(key, style, tea_offer=False):
    art = DIRECTIONS[key]
    ex = art["example"]
    plan = dict(
        original=ex["brief"],
        profile={"name": ex["brand"], "product": ex["product"]},
        subject=art["name"],
        facts="",
        shot=art["shot"],
        sector=key,
        scenePhoto=art["plate"],
    )
    plan["design"] = choose_style(plan, style)
    copy = dict(
        title=ex["title"],
        body="",
        cta=ex["cta"],
        offer="28元 / 杯" if tea_offer else ex["offer"],
        terms="仅限堂食。" if tea_offer else ex["terms"],
    )
    if style in {"riso", "ipscene", *LAYOUTS}:
        if style == "food-motion":
            plan.update(
                original="日式美食海报，居酒屋暗调",
                profile={"name": "炉边小馆", "product": "牛肉火锅"},
                scenePhoto="hotpot",
            )
            copy.update(title="趁这一锅还在冒热气", body="", offer="", terms="", cta="到店开锅。")
        elif style == "ipscene":
            plan.update(
                original="吉祥物在橘园伸手摘橘子",
                profile={"name": "橘园来信", "product": "橘子吉祥物"},
            )
            copy.update(title="摘一颗太阳", body="", offer="", terms="", cta="")
        plan["posterArt"] = direct(plan, style, plan["profile"]["product"], "")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "subject.png"
            if style in ("riso", "quiet-light"):
                scene = ROOT / "server/scenes"
                with Image.open(scene / (art["plate"] + ".webp")) as product:
                    photo = product.convert("RGBA")
                with Image.open(scene / "masks" / (art["plate"] + ".png")) as matte:
                    photo.putalpha(matte.convert("L").resize(photo.size))
                photo.save(source)
            elif style == "ipscene":
                source = (
                    Path(__file__).resolve().parent.parent
                    / "references/orchard-character.webp"
                )
            else:
                source = ROOT / "server/scenes" / (plan["scenePhoto"] + ".webp")
            scene, ink, _ = campaign_frame(
                plan, copy, None, (1080, 1440), source, None, Typesetter(), 0
            )
            scene.paste(ink, mask=ink.getchannel("A"))
            return scene
    return poster(plan, copy, None, (1080, 1440))


def save_sheet(cards, path, columns):
    width, height, gap = 348, 464, 16
    rows = (len(cards) + columns - 1) // columns
    sheet = Image.new(
        "RGB", (gap + columns * (width + gap), gap + rows * (height + 58)), "#f5f3ed"
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(SANS), 22)
    for i, (label, img) in enumerate(cards):
        x = gap + (i % columns) * (width + gap)
        y = gap + (i // columns) * (height + 58)
        sheet.paste(img.resize((width, height), Image.Resampling.LANCZOS), (x, y))
        draw.text((x, y + height + 8), label, font=font, fill="#252b24")
    sheet.save(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheets", type=Path, help="Directory for review sheets")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "public/designs")
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    industries, styles = [], []
    for key in ("tea", "commerce", "auto", "clean", "home", "retail", "beauty"):
        art = DIRECTIONS[key]
        img = sample(key, art["example"]["style"])
        img.resize((600, 800), Image.Resampling.LANCZOS).save(
            out / f"industry-{key}.webp", quality=90, method=5
        )
        industries.append((art["name"] + " · " + art["example"]["title"], img))
    for key in STYLES:
        sample_sector = {"quiet-light": "beauty", "photo-grid": "auto"}.get(key, "tea")
        img = sample(sample_sector, key, sample_sector == "tea")
        img.resize((600, 800), Image.Resampling.LANCZOS).save(
            out / f"{key}.webp", quality=90, method=5
        )
        styles.append((STYLES[key]["name"], img))
    if args.sheets:
        args.sheets.mkdir(parents=True, exist_ok=True)
        save_sheet(industries[:6], args.sheets / "响指出片-六行业海报.png", 3)
        save_sheet(styles, args.sheets / "响指出片-海报风格实排.png", 4)
        industries[-1][1].save(args.sheets / "响指出片-香水海报.png")


if __name__ == "__main__":
    main()
