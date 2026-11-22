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

    def test_middle_shot_frames_off_center_detail_and_separate_identity_mark(self):
        from server.campaign_frame import camera_window, photograph, moving_frame
        from server.visual_review import map_box

        mark = [0.2, 0.70, 0.32, 0.79]
        detail = dict(label="红色拨盘", region=[0.72, 0.15, 0.84, 0.26], source="商家框选")
        plan = dict(bundleRole="motion", profile={}, markedDetail=detail, identityRegion=mark)
        cp = dict(title="看这一处", body="前一代为黑色；活动价129元", cta="查看商品")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "original.png"
            im = Image.new("RGB", (500, 400), "#315d66")
            ImageDraw.Draw(im).rectangle((360, 60, 420, 104), fill="#ef200a")
            im.save(path)
            shot = storyboard(plan, cp, path)[1]
            self.assertEqual((shot["start"], shot["end"], shot["line"]), (3, 6, "红色拨盘"))
            for size in ((288, 512), (512, 288), (360, 360)):
                plate, box = photograph(plan, path, None, size, 2, None, False, None, shot["evidence"])
                for tick in (0, 36, 71):
                    frame = moving_frame(plate, None, 2, tick, "brisk")
                    l, t, r, b = map_box(box, camera_window(size, 2, tick, "brisk"), size)
                    for left, top, right, bottom in (mark, detail["region"]):
                        self.assertTrue(0 <= l + left * (r-l) < l + right * (r-l) <= size[0])
                        self.assertTrue(0 <= t + top * (b-t) < t + bottom * (b-t) <= size[1])
                    pixel = frame.getpixel((round(l + .78 * (r-l)), round(t + .20 * (b-t))))
                    self.assertEqual(pixel, (239, 32, 10))

    def test_local_texture_comes_from_inside_the_visible_product(self):
        from server.shot_detail import product_detail

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subject.png"
            im = Image.new("RGBA", (400, 300))
            draw = ImageDraw.Draw(im)
            draw.rectangle((170, 75, 360, 249), fill="navy")
            for x in range(190, 271, 5):
                draw.line((x, 105, x, 211), fill="white", width=2)
            im.save(path)
            detail = product_detail({}, path)
            self.assertEqual(detail["label"], "表面纹理")
            x, y, r, b = detail["region"]
            self.assertTrue(.425 < x < r < .9 and .25 < y < b < .84)
            self.assertIsNone(product_detail({"visualSource": "concept"}))
