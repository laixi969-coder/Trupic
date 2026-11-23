"""Measure and draw mixed-script text with the actual fonts used for export."""

import io
import os
import re
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import ImageFont

from .visual_review import LayoutOverflow, glyph_sample

FONT_DIR = Path(__file__).parent / "fonts"
SANS = FONT_DIR / "SourceHanSansCN-Medium.otf"
SERIF = FONT_DIR / "SourceHanSerifCN-SemiBold.otf"
LATIN = FONT_DIR / "BarlowCondensed-Bold.ttf"
# Preserve prices, brand words and punctuation at line boundaries.
TOKENS = re.compile(
    r"\n|[^\S\n]+|[¥￥$]?\d+(?:[.,:]\d+)*(?:%|％|元|折)?|[A-Za-z]+(?:['’-][A-Za-z]+)*|.",
    re.S,
)
CLOSING = "，。！？；：、）】》」”’％%.,!?:;)]"


def inspect_face(data):
    if data[:4] not in (b"OTTO", b"\0\1\0\0"):
        raise ValueError("请上传导出的单款 TTF 或 OTF 字体文件。")
    try:
        with TTFont(io.BytesIO(data)) as ft:
            if not any(table in ft for table in ("glyf", "CFF ", "CFF2")):
                raise ValueError
            table = ft.getBestCmap()
            if not table or not any(code >= 33 for code in table):
                raise ValueError
            name = ft["name"].getDebugName(4) or ft["name"].getDebugName(1)
            if not name:
                raise ValueError
            sample = "".join(
                chr(c) for c in table if 33 <= c <= 65535 and chr(c).isprintable()
            )[:6]
            ImageFont.truetype(io.BytesIO(data), 48).getmask(sample)
            return {
                "name": name[:100],
                "glyphs": len(table),
                "latin": all(ord(c) in table for c in "Trupic"),
                "cjk": any(0x3400 <= c <= 0x9FFF for c in table),
            }
    except Exception as e:
        raise ValueError(
            "无法读取此字体的字形和名称。请使用完整导出的 TTF 或 OTF。"
        ) from e


@lru_cache(maxsize=32)
def coverage(path):
    with TTFont(path, fontNumber=0, lazy=True) as ft:
        return frozenset(ft.getBestCmap() or ())


@lru_cache(maxsize=240)
def face(path, size):
    return ImageFont.truetype(str(path), size, index=0)


class Typesetter:
    def __init__(self, custom=None):
        self.custom = custom
        override = os.getenv("TRUPIC_CJK_FONT")
        self.sans = Path(override) if override and Path(override).is_file() else SANS
        self.audit_text = None
        self.editable_text = None
        self.paths = {}
        self.used = set()
        self.fallback_used = False

    def _path(self, ch, role):
        lookup = (ch, role)
        if lookup in self.paths:
            return self.paths[lookup]
        preferred = SERIF if role == "serif" else self.sans
        chain = []
        if self.custom:
            chain.append(self.custom)
        if role in ("display", "numeric") and ch.isascii():
            chain.append(LATIN)
        chain.extend((preferred, SANS, SERIF, LATIN))
        for path in dict.fromkeys(chain):
            if ord(ch) in coverage(path):
                self.paths[lookup] = path
                return path
        raise ValueError(
            f"当前字体缺少「{ch}」字形，请换用覆盖该字符的品牌字体，或调整文案。"
        )

    def runs(self, text, size, role):
        run = ""
        previous = None
        for ch in text:
            path = self._path(ch, role)
            if previous != path and run:
                yield previous, face(previous, size), run
                run = ""
            previous = path
            run += ch
        if run:
            yield previous, face(previous, size), run

    def width(self, text, size, role):
        return sum(f.getlength(run) for _, f, run in self.runs(text, size, role))

    def wrap(self, text, size, role, max_width):
        lines = []
        line = ""
        for token in TOKENS.findall(text):
            if token == "\n":
                lines.append(line.rstrip())
                line = ""
                continue
            if not line and token.isspace():
                continue
            if self.width(line + token, size, role) <= max_width:
                line += token
                continue
            if len(token) == 1 and token in CLOSING and len(line) > 1:
                lines.append(line[:-1].rstrip())
                line = line[-1] + token
                continue
            if line:
                lines.append(line.rstrip())
                line = ""
            if token.isspace():
                continue
            # A price or short brand word must shrink as a unit before it can split.
            if len(token) <= 28:
                line = token
                continue
            for ch in token:
                if line and self.width(line + ch, size, role) > max_width:
                    lines.append(line)
                    line = ""
                line += ch
        if line:
            lines.append(line.rstrip())
        return lines

    def measure(self, text, size, role, width):
        lines = self.wrap(text, size, role, width)
        rows = []
        for line in lines:
            runs = list(self.runs(line, size, role))
            boxes = [f.getbbox(run, anchor="ls") for _, f, run in runs]
            top = min((b[1] for b in boxes), default=-size)
            bottom = max((b[3] for b in boxes), default=0)
            rows.append((runs, top, bottom))
        # Common baselines prevent lines of digits and ideographs from drifting apart.
        ascent = max(-t for _, t, _ in rows)
        descent = max(b for _, _, b in rows)
        step = ascent + descent + max(2, round(size * 0.18))
        return rows, ascent, descent, step

    def draw(
        self, canvas, text, box, size, role, fill, align="left", vertical="middle"
    ):
        text = str(text or "").strip()
        if not text:
            return
        x, y, right, bottom = box
        width = right - x
        height = bottom - y
        best = None
        line_limit = (
            text.count("\n") + 1
            if role in ("display", "serif") and ("\n" in text or len(text) <= 9)
            else None
        )
        low = 7
        high = max(low, int(size))
        while low <= high:
            s = (low + high) // 2
            rows, asc, desc, step = self.measure(text, s, role, width - 3)
            actual = asc + desc + step * (len(rows) - 1)
            if (
                (line_limit is None or len(rows) <= line_limit)
                and actual <= height - 2
                and all(
                    sum(f.getlength(run) for _, f, run in runs) <= width - 2
                    for runs, _, _ in rows
                )
            ):
                best = (s, rows, asc, step, actual)
                low = s + 1
            else:
                high = s - 1
        if not best:
            raise LayoutOverflow("此段文案超出海报版面，请缩短正文或选择竖版画幅。")
        _, rows, asc, step, actual = best
        baseline = (
            y
            + asc
            + 1
            + (
                0
                if vertical == "top"
                else (height - actual - 2)
                if vertical == "bottom"
                else (height - actual - 2) / 2
            )
        )
        placements = []
        for runs, _, _ in rows:
            length = sum(f.getlength(run) for _, f, run in runs)
            pen = (
                x
                + 1
                + (
                    width - length - 2
                    if align == "right"
                    else (width - length - 2) / 2
                    if align == "center"
                    else 0
                )
            )
            for path, f, run in runs:
                placements.append(((round(pen), round(baseline)), run, f))
                pen += f.getlength(run)
                if run.strip():
                    self.used.add(" ".join(f.getname()))
                    if self.custom and path != self.custom:
                        self.fallback_used = True
            baseline += step
        if callable(fill):
            bounds = [
                canvas.textbbox(pos, run, font=font, anchor="ls")
                for pos, run, font in placements
                if run.strip()
            ]
            if not bounds:
                return
            x0, y0, x1, y1 = zip(*bounds)
            fill = fill((min(x0), min(y0), max(x1), max(y1)))
        if self.editable_text is not None:
            self.editable_text.append(
                [(pos, run, f, fill) for pos, run, f in placements]
            )
        if self.audit_text is not None:
            self.audit_text.append(glyph_sample(placements, best[0]))
        for pos, run, font in placements:
            canvas.text(pos, run, font=font, fill=fill, anchor="ls")
