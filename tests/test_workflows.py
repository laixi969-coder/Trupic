"""Acceptance coverage for billing, isolation, authenticity, revisions and rule rollout."""

import datetime as dt
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from PIL import Image

workspace = tempfile.TemporaryDirectory()
os.environ["TRUPIC_DATA"] = workspace.name
from server import app as studio
from server.creative import generate_copy, prepare


def post(client, path, **data):
    return client.post("/api/" + path, json=data)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.c = studio.app.test_client()
        self.c.get("/api/state")

    def state(self):
        return self.c.get("/api/state").json

    def plan(self, kind="poster"):
        req = dict(brief="请帮我宣传台球室，邀请朋友下班来组局。", kind=kind)
        quote = post(self.c, "preview", **req).json
        return {
            **req,
            "quote": quote["quote"],
            "confirmed": True,
            "confirmedCost": quote["cost"],
            "requestKey": uuid.uuid4().hex,
        }

    def finish(self, job):
        for _ in range(360):
            s = self.c.get("/api/jobs/" + job).json
            if s["state"] in ("complete", "failed"):
                return s
            time.sleep(0.1)
        self.fail("Generation did not finish")

    def admin(self):
        self.assertEqual(
            post(self.c, "account/admin", password=studio.ADMIN).status_code, 200
        )

    def test_consent_and_concurrent_replay(self):
        payload = self.plan()
        self.assertEqual(
            post(self.c, "jobs", **{**payload, "confirmed": False}).status_code, 400
        )
        cookie = self.c.get_cookie("trupic_workspace").value

        def submit(_):
            c = studio.app.test_client()
            c.set_cookie("trupic_workspace", cookie)
            return post(c, "jobs", **payload).json["id"]

        with ThreadPoolExecutor(max_workers=3) as ex:
            ids = list(ex.map(submit, range(3)))
        self.assertEqual(len(set(ids)), 1)
        state = self.finish(ids[0])
        self.assertEqual(state["state"], "complete", state)
        self.assertEqual(self.state()["credits"], 116)
        self.assertEqual(len(self.state()["works"]), 1)
        other = studio.app.test_client()
        other.get("/api/state")
        self.assertEqual(other.get("/api/works/" + state["work"]).status_code, 404)
        self.assertEqual(post(other, "jobs", **payload).status_code, 403)

    def test_failure_retry_only_charges_on_success(self):
        with patch.object(studio, "render", side_effect=ValueError("测试制作中断")):
            j = post(self.c, "jobs", **self.plan()).json
            self.assertEqual(self.finish(j["id"])["state"], "failed")
        self.assertEqual(self.state()["credits"], 120)
        post(self.c, "jobs/" + j["id"] + "/retry")
        self.assertEqual(self.finish(j["id"])["state"], "complete")
        post(self.c, "jobs/" + j["id"] + "/retry")
        self.assertEqual(self.state()["credits"], 116)

    def test_suggestion_and_versions(self):
        job = post(self.c, "jobs", **self.plan()).json
        self.finish(job["id"])
        url = "works/" + job["work"]
        one = self.c.get("/api/" + url).json["versions"][0]
        j = post(self.c, url + "/revise", base=1, requestKey=uuid.uuid4().hex).json
        self.assertEqual(self.finish(j["id"])["state"], "complete")
        versions = self.c.get("/api/" + url).json["versions"]
        self.assertEqual(versions[0]["title"], one["suggestion"]["title"])
        self.assertNotEqual(versions[0]["title"], versions[1]["title"])
        post(self.c, url + "/restore/1")
        self.assertEqual(self.state()["works"][0]["current"], 1)
        self.assertEqual(self.state()["credits"], 116)

    def test_unclear_material_and_private_access(self):
        stream = io.BytesIO()
        Image.new("RGB", (48, 48), "gray").save(stream, "PNG")
        stream.seek(0)
        r = self.c.post("/api/assets", data={"image": (stream, "blur.png")})
        a = r.json
        self.assertTrue(a["risk"])
        self.assertEqual(
            post(
                self.c,
                "preview",
                brief="为原图制作奶茶海报",
                kind="poster",
                asset=a["id"],
                assetConfirmed=True,
            ).status_code,
            400,
        )
        self.assertEqual(studio.app.test_client().get(a["url"]).status_code, 404)
        self.assertEqual(
            post(
                self.c, "preview", brief="帮我编造优惠价格", kind="poster"
            ).status_code,
            400,
        )
        self.assertEqual(self.state()["credits"], 120)

    def test_export_real_video_and_text(self):
        for kind in ["video", "copy"]:
            j = post(self.c, "jobs", **self.plan(kind)).json
            self.assertEqual(self.finish(j["id"])["state"], "complete")
            w = self.c.get("/api/works/" + j["work"]).json["versions"][0]
            out = self.c.get(w["download"])
            self.assertGreater(len(out.data), 30)
            if kind == "video":
                with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
                    f.write(out.data)
                    f.flush()
                    info = json.loads(
                        subprocess.check_output(
                            [
                                "ffprobe",
                                "-v",
                                "error",
                                "-show_streams",
                                "-show_format",
                                "-of",
                                "json",
                                f.name,
                            ]
                        )
                    )
                    self.assertEqual(
                        {s["codec_type"] for s in info["streams"]}, {"audio", "video"}
                    )
                    self.assertAlmostEqual(
                        float(info["format"]["duration"]), 9, places=1
                    )
            else:
                self.assertIn(w["title"], out.data.decode())
            out.close()
        self.assertEqual(self.state()["credits"], 108)

    def test_weekly_local_and_free(self):
        self.admin()
        today = dt.date.today().isoformat()
        post(
            self.c,
            "profile",
            name="春野",
            city="本地测试区",
            industry="餐饮火锅",
            product="菌菇火锅",
        )
        r = post(
            self.c,
            "admin/event",
            title="街区周末市集",
            city="本地测试区",
            starts=today,
            ends=today,
            source="https://example.org/calendar",
            verified=True,
        )
        self.assertEqual(r.status_code, 200)
        state = self.state()
        self.assertEqual(state["recs"][0]["title"], "街区周末市集")
        self.assertEqual(len(state["recs"]), 3)
        self.assertEqual(state["credits"], 120)

    def test_review_gate_and_rollback(self):
        self.assertEqual(self.c.get("/api/admin").status_code, 403)
        self.admin()
        r = post(
            self.c,
            "admin/case",
            title="测试案例",
            source="https://example.org/" + uuid.uuid4().hex,
            license="测试引用",
            kind="文案",
            category="创意方法",
            lesson="用全市第一来做承诺",
        )
        self.assertEqual(r.status_code, 200)
        case = next(
            c["id"]
            for c in self.c.get("/api/admin").json["cases"]
            if c["title"] == "测试案例"
        )
        post(self.c, "admin/approve", id=case)
        post(
            self.c,
            "admin/rule",
            name="失真测试",
            method="question",
            reason="检验门槛",
            case_id=case,
        )
        invalid = self.c.get("/api/admin").json["rules"][0]
        self.assertEqual(invalid["status"], "failed")
        self.assertEqual(
            post(self.c, "admin/release", id=invalid["id"]).status_code, 400
        )
        post(self.c, "admin/rule", name="有效问句", method="question", reason="测试")
        rule = self.c.get("/api/admin").json["rules"][0]
        self.assertEqual(post(self.c, "admin/pilot", id=rule["id"]).status_code, 200)
        self.assertEqual(post(self.c, "admin/release", id=rule["id"]).status_code, 200)
        self.assertEqual(post(self.c, "admin/rollback", id="baseline").status_code, 200)

    def test_model_facts_and_independent_review(self):
        plan = prepare(
            "帮我宣传台球室", {}, [], dict(name="S1", id="base", method="moment")
        )
        with (
            patch("server.model.engine_name", return_value="test-model"),
            patch(
                "server.model.ask",
                return_value=(
                    {"title": "开局特惠", "body": "现在只要1元", "cta": "来开球"},
                    "test-model",
                ),
            ),
        ):
            self.assertNotIn("1元", generate_copy(plan)["body"])
        result = {
            "title": "球桌边碰头",
            "body": "下班后，喊上朋友来开一局。",
            "cta": "今晚见。",
        }
        with (
            patch("server.model.engine_name", return_value="test-model"),
            patch(
                "server.model.ask",
                side_effect=[
                    (result, "test-model"),
                    (
                        {"ok": True, "headlineOk": True, "reason": "创意与资料一致"},
                        "test-model",
                    ),
                ],
            ),
        ):
            self.assertEqual(generate_copy(plan)["engine"], "test-model")

    def test_provider_and_pinterest_adapters(self):
        import base64
        from server.background import make_scene
        from server.governance import discover
        from pathlib import Path

        self.admin()
        options = dict(
            url="http://127.0.0.1:9977/v1/chat/completions",
            model="fixture",
            board="1234",
            pinToken="example-token",
            pinRights="测试素材元数据",
        )
        self.assertEqual(post(self.c, "admin/settings", **options).status_code, 200)
        try:
            model_response = io.BytesIO(
                json.dumps(
                    {"choices": [{"message": {"content": '{"ok":true}'}}]}
                ).encode()
            )
            with patch("urllib.request.urlopen", return_value=model_response):
                self.assertEqual(
                    post(self.c, "admin/test-model").json["model"], "fixture"
                )
            pins = io.BytesIO(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "19",
                                "title": "色彩与配色",
                                "description": "方法拆解",
                            }
                        ]
                    }
                ).encode()
            )
            with patch("urllib.request.urlopen", return_value=pins):
                self.assertEqual(discover(), 1)
            c = self.c.get("/api/admin").json["cases"][0]
            self.assertEqual(c["status"], "pending")
            self.assertIn("主色", c["lesson"])
            buf = io.BytesIO()
            Image.new("RGB", (512, 512), "green").save(buf, "PNG")
            visual = io.BytesIO(
                json.dumps(
                    {"data": [{"b64_json": base64.b64encode(buf.getvalue()).decode()}]}
                ).encode()
            )
            with (
                tempfile.TemporaryDirectory() as temp,
                patch(
                    "server.background.settings",
                    return_value={
                        "imageUrl": "http://localhost/render",
                        "imageModel": "fixture-image",
                        "imageKey": "",
                    },
                ),
                patch("urllib.request.urlopen", return_value=visual),
            ):
                path, name = make_scene(
                    Path(temp) / "1",
                    {
                        "subject": "花艺",
                        "goal": "相聚",
                        "angle": "邀请",
                        "shot": "送花",
                    },
                    None,
                    "poster",
                    True,
                )
                self.assertTrue(path.is_file())
                self.assertEqual(name, "fixture-image")
        finally:
            post(self.c, "admin/settings", clearKey=True)

    def test_offers_survive_short_copy_and_asset_requirement(self):
        from server.creative import draft_copy

        rule = {"name": "默认", "id": "baseline", "method": "moment"}
        p = prepare(
            "给学生写台球室周末海报，满100减20。",
            {"tone": "简洁直接", "audience": "学生"},
            [],
            rule,
        )
        copy = draft_copy(p)
        self.assertIn("满100减20", copy["offer"])
        self.assertIn("满100减20", copy["body"])
        self.assertEqual(
            post(
                self.c, "preview", brief="帮我还原包装，宣传新上市的商品", kind="poster"
            ).status_code,
            400,
        )

    def test_brand_font_import_preview_and_private_export(self):
        from server.typography import LATIN

        def upload(data):
            return self.c.post(
                "/api/fonts", data={"font": (io.BytesIO(data), "brand.ttf")}
            )

        self.assertEqual(upload(b"not a font").status_code, 400)
        font = upload(LATIN.read_bytes()).json
        self.assertFalse(font["cjk"])
        self.assertTrue(font["latin"])
        self.assertEqual(upload(LATIN.read_bytes()).json["id"], font["id"])
        self.assertEqual([x["id"] for x in self.state()["fonts"]], [font["id"]])
        specimen = "/api/fonts/" + font["id"] + "/sample.png"
        with self.c.get(specimen) as r:
            self.assertEqual(Image.open(io.BytesIO(r.data)).size, (760, 104))
        post(
            self.c,
            "profile",
            name="青屿 AOMA",
            product="抹茶拿铁",
            brandFont=font["id"],
        )
        req = {
            "brief": "抹茶拿铁周末促销，28.50元 / 杯，仅限堂食。",
            "kind": "poster",
            "ratio": "landscape",
        }
        quote = post(self.c, "preview", **req).json
        self.assertEqual(quote["plan"]["brandType"]["id"], font["id"])
        self.assertEqual(quote["plan"]["design"]["id"], "swiss")
        other = studio.app.test_client()
        self.assertEqual(other.get("/api/state").json["fonts"], [])
        self.assertEqual(other.get(specimen).status_code, 404)
        self.assertEqual(
            post(other, "preview", **req, fontId=font["id"]).status_code, 404
        )
        self.assertEqual(
            post(other, "profile", name="另一家", brandFont=font["id"]).status_code, 404
        )
        self.assertNotIn(
            "brandType", post(self.c, "preview", **req, fontId="builtin").json["plan"]
        )
        job = post(
            self.c,
            "jobs",
            **req,
            quote=quote["quote"],
            confirmed=True,
            confirmedCost=quote["cost"],
            requestKey=uuid.uuid4().hex,
        ).json
        status = self.finish(job["id"])
        self.assertEqual(status["state"], "complete", status)
        latest = self.c.get("/api/works/" + job["work"]).json["versions"][0]
        check = next(
            row["detail"] for row in latest["quality"] if row["label"] == "版式与用字"
        )
        self.assertIn("Barlow", check)
        self.assertIn("Source Han", check)
        self.assertIn("未覆盖", check)
        with self.c.get(latest["download"]) as r:
            self.assertEqual(Image.open(io.BytesIO(r.data)).size, (1920, 1080))

    def test_style_routing_and_explicit_choice(self):
        from server.design import choose_style, next_style

        for brief, style in [
            ("新品抹茶拿铁上市", "product"),
            ("街角书店品牌故事", "editorial"),
            ("演出门票28元", "screenprint"),
            ("本周蛋糕优惠", "swiss"),
        ]:
            self.assertEqual(choose_style({"original": brief})["id"], style)
        req = dict(brief="帮我宣传茶室的新品", kind="poster", ratio="feed")
        manual = post(self.c, "preview", **req, posterStyle="editorial").json
        self.assertEqual(manual["plan"]["design"]["selection"], "editorial")
        self.assertEqual(manual["ratio"], "feed")
        self.assertEqual(
            post(self.c, "preview", **req, posterStyle="unknown").status_code, 400
        )
        auto = choose_style({"original": "书店品牌故事"})
        self.assertNotEqual(next_style(auto)["id"], auto["id"])

    def test_export_settings_reach_downloaded_files(self):
        from server.formats import RATIOS, SHORT_EDGES, output_spec

        for ratio, (a, b) in RATIOS.items():
            for edge in SHORT_EDGES:
                spec = output_spec("poster", ratio, edge, 150)
                self.assertEqual(spec["width"] * b, spec["height"] * a)
                self.assertEqual(min(spec["width"], spec["height"]), edge)
        brief = "为轿车试驾设计横版商业海报。"
        self.assertEqual(
            post(
                self.c, "preview", kind="poster", brief=brief, resolution=900
            ).status_code,
            400,
        )
        self.assertEqual(
            post(self.c, "preview", kind="poster", brief=brief, dpi=200).status_code,
            400,
        )
        for kind, ratio, edge, expected in [
            ("poster", "feed", 2160, (2160, 2700)),
            ("video", "landscape", 1080, (1920, 1080)),
        ]:
            preview = post(
                self.c,
                "preview",
                brief=brief,
                kind=kind,
                ratio=ratio,
                resolution=edge,
                dpi=150,
            ).json
            job = post(
                self.c,
                "jobs",
                confirmed=True,
                confirmedCost=preview["cost"],
                quote=preview["quote"],
                requestKey=uuid.uuid4().hex,
                ratio="story",
                resolution=720,
            ).json
            result = self.finish(job["id"])
            self.assertEqual(result["state"], "complete", result)
            version = self.c.get("/api/works/" + job["work"]).json["versions"][0]
            response = self.c.get(version["download"])
            if kind == "poster":
                with Image.open(io.BytesIO(response.data)) as image:
                    self.assertEqual(image.size, expected)
                    self.assertAlmostEqual(image.info["dpi"][0], 150, delta=0.1)
            else:
                with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
                    f.write(response.data)
                    f.flush()
                    video = json.loads(
                        subprocess.check_output(
                            [
                                "ffprobe",
                                "-v",
                                "error",
                                "-select_streams",
                                "v:0",
                                "-show_streams",
                                "-of",
                                "json",
                                f.name,
                            ]
                        )
                    )["streams"][0]
                    self.assertEqual((video["width"], video["height"]), expected)
                    self.assertEqual(video["avg_frame_rate"], "24/1")
            response.close()

    def test_industry_examples_share_live_rules(self):
        from server.design import DIRECTIONS
        from server.posters import SCENES

        examples = self.state()["posterExamples"]
        self.assertEqual(len(examples), 7)
        for row in examples:
            plan = post(
                self.c,
                "preview",
                kind="poster",
                brief=row["brief"],
                posterStyle=row["style"],
            ).json["plan"]
            self.assertEqual(plan["sector"], row["id"])
            self.assertEqual(plan["scenePhoto"], DIRECTIONS[row["id"]]["plate"])
            self.assertTrue((SCENES / (plan["scenePhoto"] + ".webp")).is_file())
            self.assertNotIn("8折", row["brief"])
        for brief in (
            "给入耳式耳机做电商图",
            "为洗发水做家化上新海报",
            "为台灯做生活用品海报",
        ):
            plan = post(self.c, "preview", kind="poster", brief=brief).json["plan"]
            self.assertFalse(plan["scenePhoto"])

    def test_compositions_keep_terms_and_merchant_photo(self):
        from server.creative import draft_copy
        from server.design import STYLES, choose_style
        from server.media import SIZES
        from server.posters import poster
        from server.typography import Typesetter

        plan = prepare(
            "宣传茶室周末促销，28.50元 / 杯，仅限堂食，不可叠加其他优惠。",
            {"name": "青屿 AOMA", "product": "抹茶拿铁"},
            [],
            {"name": "基础", "id": "baseline", "method": "moment"},
        )
        copy = draft_copy(plan)
        self.assertEqual(copy["offer"], "28.50元 / 杯")
        self.assertIn("不可叠加其他优惠", copy["terms"])
        color = (16, 132, 223)

        class RecordingTypesetter(Typesetter):
            def __init__(self):
                super().__init__()
                self.lines = []

            def draw(self, canvas, text, *args, **kwargs):
                self.lines.append(text)
                return super().draw(canvas, text, *args, **kwargs)

        with tempfile.NamedTemporaryFile(suffix=".png") as source:
            Image.new("RGB", (200, 170), color).save(source.name)
            for style in STYLES:
                plan["design"] = choose_style(plan, style)
                for ratio in SIZES:
                    with self.subTest(style=style, ratio=ratio):
                        ts = RecordingTypesetter()
                        size = tuple(v // 2 for v in SIZES[ratio])
                        out = poster(plan, copy, source.name, size, typesetter=ts)
                        lines = "".join(ts.lines)
                        self.assertIn("28.50", lines)
                        self.assertIn("杯", lines)
                        self.assertIn("仅限堂食", lines)
                        self.assertIn("不可叠加其他优惠", lines)
                        self.assertNotIn("创意场景示意", lines)
                        self.assertIn(
                            color,
                            out.resize((40, 40), Image.Resampling.NEAREST).getdata(),
                        )

    def test_copy_uses_product_evidence_and_film_pays_off_opening(self):
        from server.campaign import storyboard
        from server.creative import draft_copy

        rule = dict(id="baseline", name="基础", method="moment")
        plan = prepare(
            "头戴式耳机，已确认：耳罩可拆洗。活动价129元，仅限本店。", {}, [], rule
        )
        plan["kind"] = "video"
        cp = draft_copy(plan)
        shots = storyboard(plan, cp)
        self.assertEqual([s["start"] for s in shots], [0, 3, 6])
        self.assertIn("耳罩", shots[0]["line"])
        self.assertIn("可拆洗", shots[1]["line"])
        self.assertIn("129元", shots[2]["caption"])
        self.assertIn("仅限本店", shots[2]["caption"])
        self.assertEqual(len({s["line"] for s in shots}), 3)
        self.assertNotEqual(draft_copy(plan, 1)["title"], cp["title"])
        restricted = draft_copy(
            prepare("为头戴耳机做宣传，耳罩不可拆洗。", {}, [], rule)
        )
        self.assertNotIn("拆下来洗", restricted["title"])
        locked = draft_copy(
            prepare("为抹茶拿铁做海报，标题用「山色入杯」。", {}, [], rule)
        )
        self.assertEqual(locked["title"], "山色入杯")

    def test_graphic_lettering_respects_silhouette_and_language(self):
        from server.design import DIRECTIONS
        from server.posters import SCENES
        from server.lettering import apply_lettering
        from server.typography import Typesetter
        from PIL import ImageChops

        art = DIRECTIONS["tea"]
        p = dict(sector="tea", original="抹茶拿铁新品", subject="饮品", profile={})
        with (
            Image.open(SCENES / "matcha-campaign.webp") as source,
            Image.open(SCENES / "masks/matcha-campaign.png") as mask,
        ):
            im = source.resize((256, 384)).convert("RGB")
            mask = mask.resize(im.size)
            versions = {
                mode: apply_lettering(
                    im, {**p, "lettering": mode}, Typesetter(), art, "product", mask
                )
                for mode in ("off", "han", "latin", "both")
            }
            self.assertEqual(len({v.tobytes() for v in versions.values()}), 4)
            self.assertIsNone(ImageChops.difference(im, versions["off"]).getbbox())
            delta = ImageChops.difference(im, versions["both"]).convert("L")
            self.assertIsNone(
                ImageChops.multiply(
                    delta, mask.point(lambda n: 255 if n == 255 else 0)
                ).getbbox()
            )
        self.assertEqual(
            post(
                self.c,
                "preview",
                kind="poster",
                brief="新品抹茶拿铁",
                lettering="unknown",
            ).status_code,
            400,
        )

    def test_prompt_agent_compiles_per_medium_and_persists_signed_brief(self):
        brief = "为抹茶拿铁做推广，面向午休的上班族，开头抓人，慢一点，28元 / 杯，仅限堂食，标题用「春山入盏」。"
        for kind, channels in (
            ("copy", {"copy"}),
            ("poster", {"copy", "image"}),
            ("video", {"copy", "image", "video"}),
        ):
            with patch("server.model.engine_name", return_value="本地创意规则"):
                q = post(
                    self.c,
                    "preview",
                    kind=kind,
                    brief=brief,
                    ratio="square",
                    posterStyle="product",
                ).json
            plan = q["plan"]
            compiled = plan["promptBrief"]
            self.assertEqual(set(compiled["prompts"]), channels)
            self.assertEqual(compiled["reading"]["pace"], "quiet")
            self.assertEqual(plan["method"], "question")
            self.assertEqual(plan["original"], brief)
            for term in ("28元 / 杯", "仅限堂食", "春山入盏", "午休的上班族"):
                self.assertIn(term, compiled["prompts"]["copy"])
        with patch(
            "server.app.optimize",
            side_effect=AssertionError("signed preview must be reused"),
        ):
            job = post(
                self.c,
                "jobs",
                quote=q["quote"],
                confirmed=True,
                confirmedCost=q["cost"],
                requestKey=uuid.uuid4().hex,
                brief="改成其他活动",
            ).json
            self.assertEqual(self.finish(job["id"])["state"], "complete")
        current = self.c.get("/api/works/" + job["work"]).json["versions"][0]
        self.assertEqual(current["plan"]["promptBrief"], compiled)
        self.assertEqual(current["title"], "春山入盏")

    def test_prompt_agent_model_review_and_failure_fallback(self):
        req = dict(
            kind="poster", brief="抹茶拿铁，28元 / 杯，仅限堂食", posterStyle="product"
        )
        proposal = {
            "style": "editorial",
            "product": "虚构品牌",
            "directions": {
                "copy": "用顾客端杯时的一个问题开场。",
                "image": "在杯口上方留出空间。",
            },
        }
        with patch("server.model.engine_name", return_value="fixture"):
            with patch(
                "server.model.ask",
                side_effect=[(proposal, "fixture"), ({"ok": True}, "fixture")],
            ):
                plan = post(self.c, "preview", **req).json["plan"]
            self.assertEqual(plan["design"]["id"], "product")
            self.assertNotEqual(plan["promptBrief"]["reading"]["product"], "虚构品牌")
            self.assertIn("在杯口上方留出空间", plan["promptBrief"]["prompts"]["image"])
            for responses in (
                [
                    (dict(directions={"copy": "把报价改成一元。"}), "fixture"),
                    ({"ok": False}, "fixture"),
                ],
                [TimeoutError()],
            ):
                with patch("server.model.ask", side_effect=responses):
                    plan = post(self.c, "preview", **req).json["plan"]
                self.assertEqual(plan["promptBrief"]["engine"], "本地提示词规则")
                self.assertNotIn("一元", plan["promptBrief"]["prompts"]["copy"])

    def test_wenan_skill_used_in_generation_review_and_local_workflow(self):
        from server import wenan

        brief = "洗衣液2瓶39元，本周日截止，全店可用，无需凑单。写一条不超过45字的促销消息，只给结果。"
        plan = prepare(brief, {}, [], dict(id="base", name="基础", method="moment"))
        plan["kind"] = "copy"
        with patch("server.model.engine_name", return_value="本地创意规则"):
            output = generate_copy(plan)
        self.assertEqual(output["title"], "洗衣液2瓶39元")
        self.assertEqual(output["body"], "本周日截止，全店可用，无需凑单。")
        self.assertEqual(output["cta"], "")
        self.assertEqual(output["writingSkill"]["mode"], "本地规则")
        for kind, section in [
            ("copy", "小红书、朋友圈和社媒"),
            ("poster", "广告语、海报、系列"),
            ("video", "短视频、品牌片、声音广告"),
        ]:
            plan["kind"] = kind
            with (
                patch("server.model.engine_name", return_value="fixture"),
                patch(
                    "server.model.ask",
                    side_effect=[
                        (
                            {
                                "title": "洗衣液2瓶39元",
                                "body": "本周日截止，全店可用，无需凑单。",
                                "cta": "",
                            },
                            "fixture",
                        ),
                        ({"ok": True}, "fixture"),
                    ],
                ) as ask,
            ):
                output = generate_copy(plan)
            self.assertEqual(output["writingSkill"]["mode"], "模型创作与复核")
            self.assertEqual(ask.call_count, 2)
            for call in ask.call_args_list:
                self.assertIn(wenan.CORE, call.args[0])
                self.assertIn(wenan.FORMATS[section].strip(), call.args[0])
                self.assertIn(
                    wenan.FORMATS["卖货任务：让创意推动决策"].strip(), call.args[0]
                )

    def test_wenan_sharing_and_factual_deliverables(self):
        from server import wenan
        from server.prompt_agent import optimize

        rule = dict(id="baseline", name="基础", method="moment")
        plan = prepare("为抹茶拿铁写门店海报，让顾客想拍给朋友。", {}, [], rule)
        plan["kind"] = "poster"
        optimize(dict(kind="poster", plan=plan, asset=""), infer=False)
        self.assertIn(wenan.SHARING, wenan.sections(plan))
        self.assertIn(wenan.FORMATS[wenan.SHARING].strip(), wenan.instructions(plan))
        with patch("server.model.engine_name", return_value="本地创意规则"):
            output = generate_copy(plan)
        self.assertIn("抹茶", output["title"])
        self.assertEqual(output["writingSkill"]["version"], wenan.VERSION)
        plan = prepare(
            "商品规格栏只留一行。请写明灯泡为E27螺口、额定功率8瓦，只给规格。",
            {},
            [],
            rule,
        )
        plan["kind"] = "copy"
        self.assertNotIn(wenan.SHARING, wenan.sections(plan))
        with patch("server.model.engine_name", return_value="本地创意规则"):
            output = generate_copy(plan)
        self.assertEqual(
            (output["title"], output["body"], output["cta"]),
            ("灯泡为E27螺口、额定功率8瓦", "", ""),
        )

    def test_headline_has_a_social_use_without_requesting_shares(self):
        from server import wenan
        from server.campaign import storyboard
        from server.creative import draft_copy
        from server.prompt_agent import optimize

        rule = dict(id="baseline", name="基础", method="moment")
        for kind in ("poster", "copy", "video"):
            plan = prepare("为水果店做周末宣传", {}, [], rule)
            plan["kind"] = kind
            optimize(dict(kind=kind, plan=plan, asset=""), infer=False)
            self.assertIn(wenan.HEADLINE_BRIEF, plan["promptBrief"]["prompts"]["copy"])
            draft = draft_copy(plan)
            self.assertEqual(draft["title"], "嘴硬的人，切的水果最整齐。")
            self.assertNotEqual(draft["title"], draft_copy(plan, 1)["title"])
            self.assertEqual(storyboard(plan, draft)[0]["line"], draft["title"])
        for consent in (False, None):
            review = {"ok": True}
            if consent is not None:
                review["headlineOk"] = consent
            with (
                patch("server.model.engine_name", return_value="fixture"),
                patch(
                    "server.model.ask",
                    side_effect=[
                        (
                            {
                                "title": "周末水果上新",
                                "body": "到店看看。",
                                "cta": "来看看。",
                            },
                            "fixture",
                        ),
                        (review, "fixture"),
                    ],
                ) as ask,
            ):
                self.assertEqual(generate_copy(plan)["title"], draft["title"])
                self.assertIn("单独遮住正文", ask.call_args.args[0])
        locked = prepare("宣传葡萄，标题用「葡萄到家」。", {}, [], rule)
        self.assertEqual(draft_copy(locked, 1)["title"], "葡萄到家")
        self.assertFalse(wenan.social_headline(locked))

    def test_shareable_copy_uses_the_situation_in_the_brief(self):
        from server.creative import draft_copy

        rule = dict(id="baseline", name="基础", method="moment")
        for brief, expected in (
            ("为轿车做试驾，带妈妈到店", "妈，副驾在那边。"),
            ("宣传洗衣液，瓶盖带刻度", "「倒一点」到底是哪条线？"),
            ("为百货做海报，和朋友专门来买一盒电池", "拎了两袋「顺便」，忘了买电池。"),
        ):
            with self.subTest(brief=brief):
                plan = prepare(brief, {}, [], rule)
                self.assertEqual(draft_copy(plan)["title"], expected)
                plan["recent"] = [expected]
                self.assertNotEqual(draft_copy(plan)["title"], expected)
        unsupported = prepare("宣传洗衣液，瓶盖没有刻度", {}, [], rule)
        self.assertNotIn("哪条线", draft_copy(unsupported)["title"])

    def test_closing_action_follows_goal_and_available_channel(self):
        from server.campaign import storyboard
        from server.creative import draft_copy

        rule = dict(id="baseline", name="基础", method="moment")
        for brief, expected in (
            ("轿车周末试驾，请引导私信询问时间", "私信问问周末哪天能试驾。"),
            (
                "洗衣液仅在商品页下单，没有小程序",
                "在商品页下单这款洗衣液。",
            ),
            ("百货逛街本来要买一把雨伞，周末引导到店", "周末到店，先把雨伞买上。"),
            ("给洗衣液做海报，只要主标题", ""),
        ):
            plan = prepare(brief, {}, [], rule)
            for kind in ("poster", "copy", "video"):
                plan["kind"] = kind
                draft = draft_copy(plan)
                self.assertEqual(draft["cta"], expected)
                if expected:
                    self.assertEqual(storyboard(plan, draft)[-1]["line"], expected)
        plan = prepare("为洗衣液做海报，引导小程序下单", {}, [], rule)
        with (
            patch("server.model.engine_name", return_value="fixture"),
            patch(
                "server.model.ask",
                side_effect=[
                    (
                        dict(
                            title="两件白衣一起洗",
                            body="先看看瓶身说明。",
                            cta="扫码即可了解更多。",
                        ),
                        "fixture",
                    ),
                    (dict(ok=True, headlineOk=True, closingOk=True), "fixture"),
                ],
            ),
        ):
            result = generate_copy(plan)
            self.assertEqual(result["title"], "两件白衣一起洗")
            self.assertEqual(result["cta"], "在小程序下单这款洗衣液。")

    def test_benefit_and_emotion_reach_the_headline(self):
        from server.campaign import benefit_scene, copy_route, storyboard
        from server.creative import draft_copy
        from server.prompt_agent import optimize

        rule = dict(id="baseline", name="基础", method="moment")
        for kind in ("poster", "video", "copy"):
            titles = []
            for audience, marker in (("帮朋友搬家", "纸箱"), ("回老家探望爸妈", "菜")):
                plan = prepare(
                    "宣传轿车试驾。面向" + audience + "的人。请私信询问试驾时间。",
                    {},
                    [],
                    rule,
                    facts="后排座椅可放倒",
                )
                plan["kind"] = kind
                optimize(dict(kind=kind, plan=plan, asset=""), infer=False)
                draft = draft_copy(plan)
                self.assertIn(marker, draft["title"])
                self.assertIn("放倒", draft["title"])
                self.assertIn("后排座椅可放倒", draft["body"])
                self.assertIn("私信", draft["cta"])
                scene = benefit_scene(plan, copy_route(plan))
                self.assertIn(scene["emotion"], plan["promptBrief"]["prompts"]["copy"])
                self.assertEqual(storyboard(plan, draft)[0]["line"], draft["title"])
                titles.append(draft["title"])
            self.assertNotEqual(*titles)
        for brief, facts in (
            ("给轿车做试驾海报。", ""),
            ("轿车试驾。后排可放倒，还没确认。", ""),
            ("轿车试驾。后排不能放倒。", "后排可放倒"),
            ("轿车试驾。竞品后排可放倒。", ""),
        ):
            plan = prepare(brief, {}, [], rule, facts=facts)
            self.assertIsNone(benefit_scene(plan, copy_route(plan)))
            self.assertNotIn("放倒", draft_copy(plan)["title"])
