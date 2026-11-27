"""Signed weekday offers and readback of the merchant's actual deliverables."""

import os
import re
import threading
import unicodedata
from decimal import Decimal

DAY = r"(?:周|星期|礼拜)[一二三四五六日天]"
NUMBER = r"\d{1,8}(?:\.\d{1,2})?"
AMOUNT = re.compile(
    rf"(?<![\d.])(?:(?:[¥￥]\s*({NUMBER}))(?:\s*元)?|({NUMBER})\s*元)(?![\d.])"
)
DAY_PRICE = re.compile(
    rf"(?P<day>{DAY})(?:的)?(?:到店|门店|活动|限定|特惠|优惠|专享|单杯|每杯|售|现|特)*"
    rf"(?:价(?:格)?(?:为|是)?|(?=[¥￥]))\s*[:：]?\s*[¥￥]?\s*(?P<amount>{NUMBER})(?![\d.])\s*元?"
)
AMOUNT_DAY = re.compile(
    rf"(?:[¥￥]\s*({NUMBER})\s*元?|({NUMBER})\s*元)[，,；;\s]*仅限\s*({DAY})"
)
CHANGE = re.compile(
    rf"(?:把|将)?\s*(?P<day>{DAY})?(?:的)?(?:到店|门店|活动|优惠|专享)?(?:价格|售价|价)?"
    rf"(?:从|由)?\s*[¥￥]?\s*(?P<old>{NUMBER})\s*元?\s*(?:改为|改成|调为|调整为|换成|改到)"
    rf"\s*[¥￥]?\s*(?P<new>{NUMBER})\s*元?[。！!]?\s*"
)
DIGITS = "零一二三四五六七八九"


def _day(value):
    return "周" + ("日" if value[-1] == "天" else value[-1])


def _money(value):
    return format(Decimal(value), ".2f")


def parse_change(text):
    match = CHANGE.fullmatch(unicodedata.normalize("NFKC", text or "").strip())
    if not match:
        return None
    return {
        "weekday": _day(match["day"]) if match["day"] else "",
        "old": _money(match["old"]),
        "new": _money(match["new"]),
    }


def _conflicting_claim(text):
    """A matching substring cannot confirm a negated, different-currency or ranged offer."""
    text = unicodedata.normalize("NFKC", text).translate(
        str.maketrans("週禮塊幣歐圓", "周礼块币欧元")
    )
    text = re.sub(r"\s+", "", text)
    foreign = r"(?:美元|美金|港元|港币|港纸|台币|新台币|加元|澳元|纽元|欧元|日元|日币|英镑|韩元|新币|USD|HKD|EUR|JPY|GBP|TWD|CAD|AUD|[$€£])"
    amount_start = r"[￥¥零〇一二两三四五六七八九十百千万0-9]"
    return bool(
        re.search(foreign, text, re.IGNORECASE)
        or re.search(
            rf"(?:除(?:了)?{DAY}(?:以)?外|(?:不在|非|不含|不包括|不是|不适用[于於]?|不适用于){DAY}"
            rf"|{DAY}[，,]?(?:不(?:到店|享受|适用|参加|生效|开放|是)|暂停|除外|例外)"
            rf"|(?:并非|并不是|不是|不再是|不止|不只|高于|低于|不到|多于|少于|高於|低於|起价|最低价|低至)[:：]?{amount_start}"
            rf"|(?:元|块|角|毛|分)(?:起售|起步|起[。！,，；;]|起$)|(?:不用|无需|不必|不能|不许|不可|免)到店)",
            text,
        )
    )


def confirmed_offer(brief, facts, product):
    """Read only an explicit merchant-authored weekday price, scoped to this task."""
    candidates = set()
    channels = set()
    for part in re.split(r"[。！？；;\n]", "\n".join((brief or "", facts or ""))):
        if re.search(
            r"假设|举例|例如|比如|参考价|未确认|待定|可能|拟定|不是|别用|不要|改成|改为|调为|调整为",
            part,
        ) or _conflicting_claim(part):
            continue
        for match in DAY_PRICE.finditer(part):
            candidates.add((_day(match["day"]), _money(match["amount"])))
            if "到店" in match[0]:
                channels.add("到店")
        for match in AMOUNT_DAY.finditer(part):
            candidates.add((_day(match[3]), _money(match[1] or match[2])))
    if len(candidates) > 1:
        raise ValueError("发现多组工作日价格，请指出本次作品使用的一个日期和价格。")
    if candidates:
        day, amount = candidates.pop()
        result = {
            "product": product or "",
            "weekday": day,
            "amount": amount,
            "currency": "CNY",
        }
        if channels:
            result["channel"] = "到店"
        return result


def _han_integer(number):
    if number < 10:
        return DIGITS[number]
    if number >= 10_000:
        high, low = divmod(number, 10_000)
        prefix = _han_integer(high) + "万"
        if not low:
            return prefix
        if low < 1000:
            prefix += "零"
        if 10 <= low < 20:
            prefix += "一"
        return prefix + _han_integer(low)
    result = ""
    zero = False
    for base, unit in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        digit, number = divmod(number, base)
        if digit:
            if zero:
                result += "零"
            if not (unit == "十" and digit == 1 and not result):
                result += DIGITS[digit]
            result += unit
        zero = bool(result) and bool(number) and (zero or not digit)
        if digit:
            zero = False
    return result


def _spoken(amount):
    whole, cents = _money(amount).split(".")
    jiao, fen = (int(n) for n in cents)
    return (
        _han_integer(int(whole))
        + "块"
        + (
            (DIGITS[jiao] + "毛" if jiao else "零") + DIGITS[fen] + "分"
            if fen
            else (DIGITS[jiao] if jiao else "")
        )
    )


def spoken_prices(text):
    """Pronounce currency in TTS only; keep the approved spelling in subtitles."""
    return AMOUNT.sub(lambda m: _spoken(m[1] or m[2]), text)


def replace_amount(text, change):
    """Change only currency references and explicit price fields, keeping precision."""

    def replace(m):
        amount = m[1] or m[2]
        return (
            m[0].replace(amount, change["new"], 1)
            if _money(amount) == change["old"]
            else m[0]
        )

    text = AMOUNT.sub(replace, text)

    def weekday_price(m):
        if (
            change["weekday"]
            and _day(m["day"]) != change["weekday"]
            or _money(m["amount"]) != change["old"]
        ):
            return m[0]
        return m[0].replace(m["amount"], change["new"], 1)

    return DAY_PRICE.sub(weekday_price, text)


def update_copy_and_plan(plan, cp, change):
    """Update the one offer bound to this version. Other-price campaigns need disambiguation."""
    offer = plan["merchantOffer"]
    if offer["amount"] != change["old"] or (
        change["weekday"] and change["weekday"] != offer["weekday"]
    ):
        raise ValueError("原价或适用日期与这版已确认的活动不符，请核对。")
    # When the very same amount also appears in a different weekday promotion,
    # a global numeric replacement would quietly change that other offer.
    surfaces = [
        str(cp.get(k, ""))
        for k in ("title", "body", "detailLine", "cta", "offer", "terms")
    ]
    for text in [*surfaces, plan.get("facts", ""), plan.get("original", "")]:
        days = {_day(day) for day in re.findall(DAY, text)}
        if days - {offer["weekday"]} and any(
            _money(m[1] or m[2]) == change["old"] for m in AMOUNT.finditer(text)
        ):
            raise ValueError("同一份资料有多个适用日期，请先拆分本次活动所用的价格。")

    def replace(value):
        if isinstance(value, str):
            return replace_amount(value, change)
        if isinstance(value, dict):
            return {k: replace(v) for k, v in value.items()}
        if isinstance(value, list):
            return [replace(v) for v in value]
        return value

    for field in (
        "title",
        "body",
        "detailLine",
        "cta",
        "offer",
        "terms",
        "posterDeck",
        "posterFooter",
        "socialPost",
    ):
        if field in cp:
            cp[field] = replace(cp[field])
    for field in ("facts", "profile", "coordination", "original", "promptBrief"):
        if field in plan:
            plan[field] = replace(plan[field])
    updated = {**offer, "amount": change["new"]}
    plan["merchantOffer"] = updated
    if "coordination" in plan:
        plan["coordination"]["merchantOffer"] = updated
    cp.pop("fullPosterPrompt", None)
    cp.pop("merchantOfferProof", None)


def _written_facts(text):
    text = unicodedata.normalize("NFKC", text).replace(" ", "")
    values = {_money(m[1] or m[2]) for m in AMOUNT.finditer(text)}
    # Some OCR displays the amount adjacent to 价 without its currency glyph.
    values.update(
        _money(m[1]) for m in re.finditer(rf"价(?:格)?[:：]?({NUMBER})(?![\d.])", text)
    )
    return {_day(d) for d in re.findall(DAY, text)}, values


def _audio_facts(text):
    text = unicodedata.normalize("NFKC", text).translate(
        str.maketrans("週禮點塊兩圓", "周礼点块两元")
    )
    text = re.sub(r"[\s,，。！？!？]", "", text)
    spoken_digits = "零〇一二两三四五六七八九十百千万0123456789"

    def integer(value):
        if value.isascii() and value.isdigit():
            return int(value)
        if "万" in value:
            high, low = value.split("万", 1)
            return integer(high) * 10000 + (integer(low) if low else 0)
        total, digit = 0, ""
        for ch in value.replace("两", "二").replace("〇", "零"):
            if ch in "十百千":
                total += int(digit or 1) * {"十": 10, "百": 100, "千": 1000}[ch]
                digit = ""
            else:
                digit += ch if ch.isascii() else str(DIGITS.index(ch))
        return total + int(digit or 0)

    amounts = set()
    normalized = re.sub(DAY, " ", text.replace("圆", "元"))
    count = rf"[{spoken_digits}]+"
    fraction = r"[零〇一二两三四五六七八九0-9]"
    # Consume the fractional part before attempting the next currency match.
    pattern = (
        rf"({count})(?:[.点]({fraction}{{1,2}}))?[元块]"
        rf"(?:({fraction})[角毛](?:({fraction})分)?|零({fraction})分|({fraction})(?!杯|份|件|盒|袋|瓶|个))?"
    )
    for m in re.finditer(pattern, normalized):
        decimal = m[2]
        if decimal is not None:
            cents = "".join(str(integer(ch)) for ch in decimal).ljust(2, "0")
        else:
            cents = str(integer(m[3] or m[6] or "0")) + str(
                integer(m[4] or m[5] or "0")
            )
        amounts.add(_money(str(integer(m[1])) + "." + cents))
    # Whisper sometimes formats the fraction as a single decimal without 元.
    for m in re.finditer(r"(?<![\d.])(\d+\.\d{1,2})(?![\d.])", normalized):
        amounts.add(_money(m[1]))
    return {_day(d) for d in re.findall(DAY, text)}, amounts


def require_facts(text, offer, surface, *, audio=False):
    days, amounts = (_audio_facts if audio else _written_facts)(text)
    if (
        days != {offer["weekday"]}
        or amounts != {offer["amount"]}
        or _conflicting_claim(text)
        or offer.get("channel")
        and offer["channel"] not in re.sub(r"\s+", "", text)
    ):
        raise ValueError(
            f"{surface}未核实到唯一的{offer['weekday']}活动价 {offer['amount']} 元。"
            f"实际读回：{text[:180] or '未读到内容'}"
        )


def bind_script(draft, offer, *, supplied=False):
    """A generated CTA may be completed before the quote is shown; signed words are immutable."""
    if not offer:
        return
    words = "".join(draft.get(key, "") for key in ("title", "detailLine", "cta"))
    days, amounts = _written_facts(words)
    expected = offer["amount"]
    if (
        (days - {offer["weekday"]})
        or (amounts - {expected})
        or _conflicting_claim(words)
    ):
        raise ValueError("分镜稿与确认的工作日或价格不符，请核对活动资料。")
    if (
        amounts != {expected}
        or days != {offer["weekday"]}
        or offer.get("channel")
        and offer["channel"] not in words
    ):
        if supplied:
            raise ValueError(
                f"请在三镜定稿中写明{offer['weekday']}价格 {expected} 元，或调整本次活动资料。"
            )
        draft["cta"] = f"{offer['weekday']}{offer.get('channel', '')}{expected}元。"
    # These fields are metadata used by layout and post generation as well.
    draft["offer"] = f"{expected}元"
    draft["terms"] = offer["weekday"]


def campaign_poster(folder, asset, offer):
    """Deliver a separate mobile poster using the original uploaded product photo."""
    from pathlib import Path

    from PIL import Image, ImageDraw, ImageFont, ImageOps

    from .typography import Typesetter

    with Image.open(asset) as image:
        photo = ImageOps.contain(ImageOps.exif_transpose(image).convert("RGBA"), (930, 885),
                                 Image.Resampling.LANCZOS)
    poster = Image.new("RGB", (1080, 1440), "#F5F2E9")
    draw = ImageDraw.Draw(poster)
    ink, accent = "#192D25", "#25563A"
    fonts = Path(__file__).parent / "fonts"

    def font(size):
        return ImageFont.truetype(str(fonts / "SourceHanSansCN-Medium.otf"), size)

    product = offer["product"]
    ts = Typesetter()
    ts.draw(draw, product, (75, 45, 1004, 204), 93, "serif", lambda bounds: ink)
    draw.line((75, 215, 1005, 215), fill="#CBD0BE", width=2)
    poster.paste(
        photo, ((1080 - photo.width) // 2, 248 + (885 - photo.height) // 2), photo
    )
    draw.rectangle((0, 1170, 1080, 1440), fill=accent)
    day = offer["weekday"] + (offer.get("channel") or "活动") + "价"
    draw.text((75, 1203), day, font=font(46), fill="#FFFFFF")
    draw.text((70, 1264), "¥" + offer["amount"], font=font(92), fill="#FFFFFF")
    poster.save(folder / "offer-poster.png", dpi=(144, 144))


def _ocr(images):
    from rapidocr import ModelType, OCRVersion, RapidOCR

    with _OCR_LOCK:
        global _OCR_ENGINE
        if _OCR_ENGINE is None:
            params = {
                "Det.ocr_version": OCRVersion.PPOCRV5,
                "Det.model_type": ModelType.MOBILE,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
                "Global.use_cls": False,
            }
            if model_dir := os.getenv("TRUPIC_OCR_MODEL_DIR"):
                from pathlib import Path

                params["Global.model_root_dir"] = str(
                    Path(model_dir).expanduser().resolve()
                )
            _OCR_ENGINE = RapidOCR(params=params)
        rows = []
        for path in images:
            result = _OCR_ENGINE(str(path))
            rows.append(
                [
                    {
                        "text": txt,
                        "confidence": round(float(score), 4),
                        "box": [
                            int(box[:, 0].min()),
                            int(box[:, 1].min()),
                            int(box[:, 0].max()),
                            int(box[:, 1].max()),
                        ],
                    }
                    for txt, score, box in zip(
                        result.txts or (),
                        result.scores or (),
                        result.boxes if result.boxes is not None else (),
                    )
                ]
            )
        return rows


_OCR_LOCK = threading.Lock()
_OCR_ENGINE = None


def _verify_readings(rows, offer, label):
    # A low confidence conflict is also a reason to hold the delivery for review.
    all_text = "".join(r["text"] for r in rows)
    require_facts(all_text, offer, label)
    sure = "".join(r["text"] for r in rows if r["confidence"] >= 0.8)
    require_facts(sure, offer, label + "（清晰度）")


def check_delivery(folder, plan, kind):
    """Verify the exported posting copy, PNG and both streams of the final MP4."""
    import io
    import json
    import subprocess
    import tempfile
    import zipfile
    from pathlib import Path

    from PIL import Image

    from .voice import transcribe

    offer = plan.get("merchantOffer")
    if not offer:
        return None
    post = (folder / "copy.txt").read_text(encoding="utf-8")
    require_facts(post, offer, "发布配文")
    proof = {"offer": offer, "post": post}
    if kind == "copy":
        return proof
    if kind != "video":
        return proof
    srt = (folder / "captions.srt").read_text(encoding="utf-8")
    text = " ".join(
        line for line in srt.splitlines() if "-->" not in line and not line.isdigit()
    )
    require_facts(text, offer, "逐镜 SRT 字幕")
    proof["srt"] = text.strip()
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        tmp = Path(tmp)
        full_poster = folder / "offer-poster.png"
        # The merchant's source photo can include a printed reference price.
        # Read the campaign panel only; packaging is verified independently.
        panel = tmp / "offer.png"
        with Image.open(full_poster) as poster:
            poster.crop((0, 1170, 1080, 1440)).save(panel)
        frames = []
        with zipfile.ZipFile(folder / "edit.zip") as bundle:
            timeline = json.loads(bundle.read("timeline.json"))
            for index, cue in enumerate(timeline["captions"]):
                when = (cue["startFrame"] + cue["endFrame"] - 1) / (2 * timeline["fps"])
                path = tmp / f"cue-{index}.png"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-ss",
                        str(when),
                        "-i",
                        str(folder / "video.mp4"),
                        "-frames:v",
                        "1",
                        str(path),
                    ],
                    check=True,
                    timeout=30,
                )
                with Image.open(io.BytesIO(bundle.read(cue["layer"]))) as layer:
                    bounds = layer.getchannel("A").getbbox()
                if not bounds:
                    raise ValueError("成片字幕图层为空，请检查对应镜头。")
                title_name = timeline["shots"][cue["shotIndex"]]["titleLayer"]
                with Image.open(io.BytesIO(bundle.read(title_name))) as title:
                    title_alpha = title.getchannel("A")
                frames.append((path, when, bounds, title_alpha))
        readbacks = _ocr([panel, *(entry[0] for entry in frames)])
        _verify_readings(readbacks[0], offer, "活动海报")
        proof["poster"] = {"filename": full_poster.name, "readback": readbacks[0]}
        proof["burnedCaptions"] = []
        for (_, when, (left, top, right, bottom), title), rows in zip(
            frames, readbacks[1:]
        ):
            # Recognition on the entire frame preserves text scale. Select only
            # glyphs in the encoded subtitle/title locations to exclude packaging.
            caption_rows, title_rows = [], []
            for row in rows:
                x0, y0, x1, y1 = row["box"]
                if left <= (x0 + x1) / 2 <= right and top <= (y0 + y1) / 2 <= bottom:
                    caption_rows.append(row)
                elif title.crop((x0, y0, x1, y1)).getbbox():
                    title_rows.append(row)
            title_text = "".join(row["text"] for row in title_rows)
            days, amounts = _written_facts(title_text)
            if (
                days - {offer["weekday"]}
                or amounts - {offer["amount"]}
                or _conflicting_claim(title_text)
            ):
                raise ValueError(f"MP4 镜头文字与活动资料有出入：{title_text}")
            proof["burnedCaptions"].append(
                {
                    "second": round(when, 3),
                    "readback": caption_rows,
                    "titleReadback": title_rows,
                }
            )
        _verify_readings(
            [line for cue in proof["burnedCaptions"] for line in cue["readback"]],
            offer,
            "MP4 内嵌字幕",
        )
        # Inspect actual final AAC rather than the clean synthesis input or alignment text.
        wav = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(folder / "video.mp4"),
                "-map",
                "0:a:0",
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                "-",
            ],
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        transcript = transcribe(wav, tmp)
        require_facts(transcript, offer, "成片口播", audio=True)
        proof["spoken"] = transcript
    return proof


if __name__ == "__main__":
    import argparse
    import tempfile
    from pathlib import Path

    from PIL import Image

    parser = argparse.ArgumentParser(description="预装并验证活动价读回模型")
    parser.add_argument("--prepare-ocr", action="store_true", required=True)
    parser.parse_args()
    sample_offer = {
        "product": "抹茶拿铁",
        "weekday": "周五",
        "amount": "19.90",
        "channel": "到店",
        "currency": "CNY",
    }
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        campaign_poster(
            folder, Path(__file__).parent / "scenes/matcha.webp", sample_offer
        )
        with Image.open(folder / "offer-poster.png") as sample:
            sample.crop((0, 1170, 1080, 1440)).save(folder / "panel.png")
        rows = _ocr([folder / "panel.png"])[0]
        _verify_readings(rows, sample_offer, "预检海报")
        print(
            "中文检测、识别模型就绪。实际读回：" + "".join(row["text"] for row in rows)
        )
