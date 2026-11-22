"""Regression checks for omissions found while inspecting real skill exports."""

import tempfile
import re
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from server.campaign import storyboard
from server.skill_render import render_product
from server.typography import Typesetter


class SkillLayoutTests(unittest.TestCase):
    def test_confirmed_information_is_visible_in_each_applicable_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "subject.png"
            source = Image.new("RGBA", (800, 800))
            ImageDraw.Draw(source).rectangle((240, 160, 560, 640), fill="#45613d")
            source.save(path)
            cp = dict(
                title="春山抹茶粉",
                body="11月25日 19:30开播 · 100g罐装 · 48元/罐",
                terms="11月25日至30日，仅限单罐装",
            )
            for role, dims in (
                ("hero", (1080, 1080)),
                ("livecover", (1080, 1920)),
                ("announcement", (1080, 1920)),
                ("detail", (1080, 1440)),
                ("banner", (1920, 1080)),
                ("price", (1080, 1080)),
            ):
                with self.subTest(role=role):
                    ts = Typesetter()
                    ts.audit_text = []
                    render_product(dict(bundleRole=role), cp, path, dims, ts)
                    text = "".join(row[3] for row in ts.audit_text)
                    self.assertIn(cp["title"], text)
                    normalize = lambda v: re.sub(r"[\s·]+", "", v)
                    self.assertIn(normalize(cp["body"]), normalize(text))
                    if role in ("banner", "price"):
                        self.assertIn(cp["terms"], text)
                    self.assertGreaterEqual(min(row[2] for row in ts.audit_text), 27)

    def test_transparent_margins_do_not_shrink_the_visible_product(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "subject.png"
            source = Image.new("RGBA", (1000, 1000))
            ImageDraw.Draw(source).rectangle((400, 300, 600, 700), fill="#345a32")
            source.save(path)
            ts = Typesetter()
            ts.audit_text = []
            image, box = render_product(
                dict(bundleRole="white"),
                dict(title="", body="", terms=""),
                path,
                (1080, 1080),
                ts,
            )
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
            # Visible source bounds map to a product 80% of the output's height.
            height = (701 - 300) / 1000 * (box[3] - box[1])
            self.assertAlmostEqual(height, 864, delta=2)

    def test_video_middle_shot_uses_approved_facts_not_example_copy(self):
        plan = dict(
            bundleRole="motion",
            profile={"name": "春山"},
            posterArt={"detail": "不相关的旧示例"},
        )
        cp = dict(
            title="春山抹茶粉",
            body="100g罐装 · 搭配牛奶冲调",
            cta="查看规格",
            offer="48元/罐",
            terms="仅限单罐装",
        )
        shots = storyboard(plan, cp)
        self.assertEqual(shots[1]["line"], cp["body"])
        self.assertEqual(shots[2]["line"], cp["cta"])
        self.assertIn(cp["terms"], shots[2]["caption"])
