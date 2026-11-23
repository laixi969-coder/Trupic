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
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from PIL import Image

workspace = tempfile.TemporaryDirectory()
os.environ["TRUPIC_DATA"] = workspace.name
from server import app as studio
from server.creative import generate_copy, prepare


def post(client, path, **data):
    return client.post("/api/" + path, json=data)


def submit_revision(client, path, **data):
    quote = post(client, path.removesuffix("/revise")+"/revision-quote", **data)
    assert quote.status_code == 200, quote.json
    return post(client, path, **data, quote=quote.json["quote"], confirmed=True, confirmedCost=quote.json["cost"])


def submit_with_copy(client, path, **data):
    """Select a deterministic fixture when testing the downstream rendering pipeline."""
    from server.copy_choices import proposal_specs

    token = data.get("quote")
    if token and "copyChoice" not in data:
        q = studio.quotes.loads(token)
        spec = next((s for s in proposal_specs(q) if s["kind"] == "poster"), None)
        if spec:
            base = {**studio.draft_copy(spec["plan"]), **spec.get("replacement", {})}
            import hashlib
            data["copyChoice"] = studio.quotes.dumps(
                {"quoteId": hashlib.sha256(token.encode()).hexdigest(), "draft": base},
                salt="trupic-copy-choice",
            )
    return post(client, path, **data)


class WorkflowTests(unittest.TestCase):
    def test_moment_reference_edit_passes_the_photo_and_reuses_the_scene(self):
        import base64
        from pathlib import Path
        from server.background import generate_scene
        selected = dict(provider="custom", url="https://images.example/v1/images/generations",
                        model="gpt-image-2", key="")
        plan = dict(subject="水杯", goal="日常分享", angle="喝水提醒", shot="杯盖",
                    moment={"headline": "收到，请回「吨」。"}, design={"photoLayout": "reply", "scene": "实拍"},
                    output={"width": 1080, "height": 1920})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (300, 650), "green").save(root / "original.png")
            rendered = io.BytesIO()
            Image.new("RGB", (400, 640), "cyan").save(rendered, format="PNG")
            response = json.dumps({"data": [{"b64_json": base64.b64encode(rendered.getvalue()).decode()}]})
            with patch("server.region_edit.urllib.request.build_opener") as opener:
                opener.return_value.open.return_value = io.BytesIO(response.encode())
                args = selected, root / "works" / "1", plan, root / "subject.png", "poster"
                first = generate_scene(*args, fresh=True, strict=False)
                self.assertEqual(first[1], selected["model"])
                self.assertTrue(first[0].is_file())
                self.assertEqual(generate_scene(*args, fresh=False, strict=False), first)
                opener.return_value.open.assert_called_once()
                req = opener.return_value.open.call_args.args[0]
                self.assertEqual(req.full_url, "https://images.example/v1/images/edits")
                self.assertIn(plan["moment"]["headline"].encode(), req.data)
                self.assertIn(b"\x89PNG", req.data)
                self.assertIn(b"1008x1792", req.data)

    def test_matte_fringe_and_measured_text_do_not_imply_clipping(self):
        from pathlib import Path
        from server.product_bundle import qualified_cutout
        from server.visual_review import measured_separation
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subject.png"
            photo = Image.new("RGBA", (300, 300))
            pen = ImageDraw.Draw(photo)
            pen.rectangle((30, 60, 298, 230), fill=(30, 30, 30, 255))
            info = dict(path=path, risk=False, file=path.name)
            for alpha, intact in ((124, True), (255, False)):
                pen.line((299, 90, 299, 120), fill=(30, 30, 30, alpha))
                photo.save(path)
                self.assertEqual(qualified_cutout(info, True), intact)
        frame = dict(subjectBounds=(30, 125, 260, 270), size=(300, 300))
        for box, separate in (((15, 12, 220, 80), True), ((15, 12, 220, 160), False),
                              ((-8, 12, 220, 80), False)):
            self.assertEqual(measured_separation({**frame, "text": [(box, None, 20, "标题")]}), separate)

    def test_phone_mpo_jpeg_uses_primary_image(self):
        image = Image.new("RGB", (250, 260), "red")
        upload = io.BytesIO()
        image.save(upload, format="MPO", save_all=True,
                   append_images=[Image.new("RGB", image.size, "blue")])
        upload.seek(0)
        from pathlib import Path
        from server.media import inspect_upload
        with tempfile.TemporaryDirectory() as folder:
            inspect_upload(upload, Path(folder))
            with Image.open(Path(folder) / "original.png") as primary:
                self.assertEqual(primary.size, image.size)
                self.assertGreater(primary.getpixel((100, 100))[0], 250)

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

    def bundle_plan(self, cutout=False):
        with Image.open("server/scenes/matcha.webp") as source:
            photo = source.convert("RGBA").resize((500, 500))
        if cutout:
            canvas = Image.new("RGBA", (700, 700))
            canvas.paste(photo, (100, 100))
            photo = canvas
        stream = io.BytesIO()
        photo.save(stream, format="PNG")
        stream.seek(0)
        with patch.dict(os.environ, {"TRUPIC_CUTOUT": "/missing"}):
            asset = self.c.post("/api/assets", data={"image": (stream, "product.png")}).json
        response = post(self.c, "bundles/preview", title="抹茶饮品", benefits="抹茶与牛奶搭配", asset=asset["id"], assetConfirmed=True, ratio="square", resolution=720)
        self.assertEqual(response.status_code, 200, response.json)
        q = response.json
        return q, dict(quote=q["quote"], confirmed=True, confirmedCost=q["cost"], requestKey=uuid.uuid4().hex)

    def test_v3_signed_specs_balance_reservations_and_trash(self):
        self.admin()
        self.assertEqual(post(self.c,"profile",industryTags=["台球","休闲"],name="").status_code,200)
        q = post(self.c,"creations/plan",brief="宣传周末台球组局",promotedItem="双人台球",deliveryMode="image",imageCount=2,ratio="square").json
        self.assertEqual([i["kind"] for i in q["deliveries"]],["copy","poster","poster"])
        rates=self.c.get("/api/admin/pricing").json
        try:
            post(self.c,"admin/pricing",**{**rates,"poster":9})
            with patch.object(studio.pool,"submit"):
                run=post(self.c,"creations",quote=q["quote"],confirmedCost=8,requestKey="v3").json
                self.assertEqual(self.state()["credits"],112)
                for i in run["items"]:
                    studio.produce(i["job"])
            self.assertEqual(self.state()["credits"],112)
            works=self.state()["works"]
            poster=next(w for w in works if w["kind"]=="poster")
            path="works/"+poster["id"]
            v=self.c.get("/api/"+path).json["versions"][0]
            self.assertEqual(v["plan"]["industryTags"],["台球","休闲"])
            self.assertEqual(v["plan"]["promotedItem"],"双人台球")
            self.assertEqual(v["plan"]["output"]["width"],v["plan"]["output"]["height"])
            self.assertEqual(post(self.c,path+"/revise",requestKey="no-quote").status_code,400)
            quote=post(self.c,path+"/revision-quote",action="ratio",ratio="landscape").json
            with patch.object(studio.pool,"submit"):
                j=post(self.c,path+"/revise",quote=quote["quote"],confirmedCost=quote["cost"],confirmed=True,requestKey="resize").json
                studio.produce(j["id"])
            self.assertNotEqual(j["work"],poster["id"])
            self.assertEqual(self.c.get("/api/jobs/"+j["id"]).json["state"],"complete")
            self.assertEqual(self.c.get("/api/"+path).json["current"],1)
            other=studio.app.test_client()
            self.assertEqual(post(other,"works/trash",ids=[poster["id"]]).status_code,404)
            batch=post(self.c,"works/trash",ids=[poster["id"]]).json["batch"]
            self.assertEqual(self.c.get("/api/"+path).status_code,404)
            group=self.c.get("/api/creations/"+run["id"]).json
            self.assertNotIn(poster["id"],[i["work"] for i in group["items"]])
            self.assertEqual(post(other,"works/trash/"+batch+"/undo").json["count"],0)
            self.assertEqual(post(self.c,"works/trash/"+batch+"/undo").json["count"],1)
            self.assertEqual(self.c.get("/api/"+path).status_code,200)
        finally:
            post(self.c,"admin/pricing",**{**rates,"version":self.c.get("/api/admin/pricing").json["version"]})

    def test_v3_signed_payments_and_invite_milestones(self):
        import hashlib,hmac
        self.admin()
        who=uuid.uuid4().hex
        post(self.c,"account/register",login=who,password="fixture-account")
        rules=self.c.get("/api/admin/growth").json["rules"]
        post(self.c,"admin/growth",**{**rules,"action":"rules","paidOwner":7,"generateGuest":3})
        code=self.c.get("/api/promotion").json["codes"]["merchant"]
        guest=studio.app.test_client()
        login=uuid.uuid4().hex
        post(guest,"account/register",login=login,password="fixture-account",invite=code)
        for name in (who,login):
            post(self.c,"admin/growth",action="verify",login=name,identity=name)
        q=post(guest,"creations/plan",brief="周末台球组局",deliveryMode="image",ratio="square").json
        with patch.object(studio.pool,"submit"):
            run=post(guest,"creations",quote=q["quote"],confirmedCost=q["cost"],requestKey="first").json
            for item in run["items"]:
                studio.produce(item["job"])
        self.assertEqual(guest.get("/api/state").json["credits"],119)
        offer=post(self.c,"admin/offers",cycle="year",name="测试年费",cents=1000,credits=50,bonus=5).json[0]
        with patch.dict(os.environ,{"TRUPIC_CHECKOUT_URL":"https://checkout.invalid","TRUPIC_PAYMENT_SECRET":"test-key"}):
            oid=post(guest,"orders",offer=offer["id"],cents=1000,credits=50,bonus=5,requestKey="order1").json["id"]
            data=json.dumps(dict(order=oid,status="paid",currency="CNY",cents=1000,receipt=uuid.uuid4().hex)).encode()
            stamp=str(int(time.time()))
            sig=hmac.new(b"test-key",stamp.encode()+b"."+data,hashlib.sha256).hexdigest()
            self.assertEqual(guest.post("/api/payments/webhook",data=data,content_type="application/json").status_code,403)
            for _ in range(3):
                self.assertEqual(guest.post("/api/payments/webhook",data=data,content_type="application/json",headers={"X-Payment-Timestamp":stamp,"X-Payment-Signature":sig}).status_code,200)
        self.assertEqual(guest.get("/api/state").json["credits"],174)
        self.assertEqual(self.state()["credits"],127)
        self.assertEqual(guest.get("/api/state").json["videoDurations"],[15,30,45])
        self.assertEqual(post(self.c,"creations/plan",brief="周末组局",deliveryMode="video",ratio="square",duration=45).status_code,400)
        post(self.c,"admin/growth",action="rules",**rules)

    def test_v3_channel_coupon_refund_and_staff_isolation(self):
        from server import commerce, coupons, growth
        self.admin()
        login=uuid.uuid4().hex
        agent=studio.app.test_client()
        post(agent,"account/register",login=login,password="channel-fixture")
        post(self.c,"admin/growth",action="agent",login=login,role="区县代理")
        rule=self.c.get("/api/admin/growth").json["rules"]
        post(self.c,"admin/growth",action="rules",**{**rule,"firstBps":1000})
        promo=agent.get("/api/promotion").json
        code=promo["codes"]["agent"]
        with agent.get("/api/promotion/"+code+"/qr") as qr:
            self.assertEqual(qr.mimetype,"image/png")
        guest=studio.app.test_client()
        guest_login=uuid.uuid4().hex
        post(guest,"account/register",login=guest_login,password="guest-fixture",invite=code)
        self.assertEqual(agent.get("/api/promotion").json["clients"][0]["login"],guest_login)
        self.assertEqual(agent.get("/api/admin/merchants").status_code,403)
        self.assertEqual(self.c.get("/api/promotion").json["clients"],[])
        offer=post(self.c,"admin/offers",name="测试套餐",cycle="month",cents=1000,credits=10,bonus=2).json[0]
        coupon=post(self.c,"admin/coupons",offer=offer["id"],discount=120,threshold=500,quantity=1,per_user=1,
                    starts=studio.now()[:10],ends=studio.now()[:10],agent=login).json[0]["code"]
        self.assertEqual(post(agent,"orders/price",offer=offer["id"],coupon=coupon).status_code,400)
        self.assertEqual(post(guest,"orders/price",offer=offer["id"],coupon=coupon).json["cents"],880)
        with patch.dict(os.environ,{"TRUPIC_CHECKOUT_URL":"https://pay.invalid","TRUPIC_PAYMENT_SECRET":"test"}):
            oid=post(guest,"orders",offer=offer["id"],credits=10,bonus=2,cents=880,coupon=coupon,requestKey="first").json["id"]
            self.assertEqual(post(guest,"orders/price",offer=offer["id"],coupon=coupon).status_code,400)
        with studio.db(True) as c:
            row=c.execute("SELECT * FROM purchase WHERE id=?",(oid,)).fetchone()
            commerce.fulfill(c,row,"receipt-"+oid)
        sale=agent.get("/api/promotion").json["commissions"][0]
        self.assertEqual(sale["amount"],88)
        self.assertEqual(guest.get("/api/state").json["credits"],132)
        self.assertEqual(post(agent,"admin/growth",action="settle",order=oid).status_code,403)
        post(self.c,"admin/growth",action="settle",order=oid)
        with studio.db(True) as c:
            for _ in range(2):
                row=c.execute("SELECT * FROM purchase WHERE id=?",(oid,)).fetchone()
                commerce.refund(c,row,"receipt-"+oid)
        self.assertEqual(guest.get("/api/state").json["credits"],120)
        self.assertEqual(agent.get("/api/promotion").json["commissions"][0]["status"],"recovery_due")
        post(self.c,"admin/staff",login=login,role="support")
        self.assertEqual(agent.get("/api/admin").json["allowedTabs"],["merchants"])
        self.assertEqual(agent.get("/api/admin/merchants").status_code,200)
        self.assertEqual(agent.get("/api/admin/pricing").status_code,403)
        post(self.c,"admin/growth",action="rules",**rule)

    def test_growth_joint_source_rules_history_and_settlement(self):
        from server import commerce, growth

        self.admin()
        original = self.c.get("/api/admin/growth").json["rules"]

        def admin(action, **values):
            response = post(self.c, "admin/growth", action=action, **values)
            self.assertEqual(response.status_code, 200, response.json)
            return response.json

        def merchant(**params):
            client = studio.app.test_client()
            login = uuid.uuid4().hex
            response = post(
                client,
                "account/register",
                login=login,
                password="test-merchant",
                **params,
            )
            self.assertEqual(response.status_code, 200, response.json)
            admin("verify", login=login, identity=login)
            return client, login

        def promo(client):
            return client.get("/api/promotion").json

        team, team_login = merchant()
        other, other_login = merchant()
        agent, agent_login = merchant()
        for name in (team_login, other_login):
            admin("agent", login=name, role="团队负责人")
        admin("agent", login=agent_login, parent=team_login, role="个人推广员")
        self.assertEqual(promo(team)["team"][0]["login"], agent_login)
        rep = promo(agent)["codes"]["agent"]
        inviter, owner_login = merchant(invite=rep)
        invite = promo(inviter)["codes"]["merchant"]
        self.assertEqual(promo(inviter)["channel"], rep)
        self.assertEqual(
            inviter.get(f"/api/promotion/{invite}/qr?channel={rep}").mimetype,
            "image/png",
        )
        offer = post(
            self.c,
            "admin/offers",
            name="联合推广验收",
            cycle="month",
            cents=1000,
            credits=10,
            bonus=0,
        ).json[0]

        def order(client, **kwargs):
            result = post(
                client,
                "orders",
                offer=offer["id"],
                credits=10,
                bonus=0,
                cents=1000,
                requestKey=uuid.uuid4().hex,
                **kwargs,
            )
            self.assertEqual(result.status_code, 200, result.json)
            return result.json["id"]

        def pay(oid, **kwargs):
            with studio.db(True) as c:
                row = c.execute("SELECT * FROM purchase WHERE id=?", (oid,)).fetchone()
                commerce.fulfill(c, row, "r-" + oid, **kwargs)

        try:
            with patch.dict(
                os.environ,
                {
                    "TRUPIC_CHECKOUT_URL": "https://checkout.invalid",
                    "TRUPIC_PAYMENT_SECRET": "fixture",
                },
            ):
                for policy, reward, amount in [
                    ("both", 7, 100),
                    ("agent", 0, 100),
                    ("merchant", 7, 0),
                ]:
                    config = {
                        **original,
                        "overlap": policy,
                        "firstBps": 1000,
                        "paidOwner": 7,
                        "paidGuest": 5,
                    }
                    admin("rules", **config)
                    guest, login = merchant(invite=invite, channel=rep)
                    before = inviter.get("/api/state").json["credits"]
                    oid = order(guest)
                    admin("rules", **{**config, "paidOwner": 99, "firstBps": 8000})
                    pay(oid)
                    pay(oid)
                    self.assertEqual(
                        inviter.get("/api/state").json["credits"], before + reward
                    )
                    self.assertEqual(
                        guest.get("/api/state").json["credits"],
                        130 + (5 if reward else 0),
                    )
                    commissions = [
                        r for r in promo(team)["commissions"] if r["order_id"] == oid
                    ]
                    self.assertEqual(sum(r["amount"] for r in commissions), amount)
                    self.assertEqual(bool(commissions), bool(amount))
                admin("rules", **{**config, "overlap": "both", "settleDays": 2})
                first, _ = merchant(invite=invite, channel=rep)
                first_order = order(first)
                pay(first_order, payer="gateway-shared-test")
                self.assertEqual(
                    post(
                        self.c, "admin/growth", action="settle", order=first_order
                    ).status_code,
                    400,
                )
                second, _ = merchant(invite=invite, channel=rep)
                second_order = order(second)
                before = inviter.get("/api/state").json["credits"]
                pay(second_order, payer="gateway-shared-test")
                self.assertEqual(inviter.get("/api/state").json["credits"], before)
                admin("reject-payer", order=second_order, reference="重复付款身份复核")
                self.assertEqual(inviter.get("/api/state").json["credits"], before)
                self.assertEqual(
                    next(
                        r["status"]
                        for r in promo(agent)["commissions"]
                        if r["order_id"] == second_order
                    ),
                    "disqualified",
                )
                admin("rules", **{**config, "ends": "2000-01-01"})
                guest, login = merchant(invite=invite, channel=rep)
                before = inviter.get("/api/state").json["credits"]
                oid = order(agent, merchant=login)
                self.assertEqual(
                    post(
                        other, "orders/price", merchant=login, offer=offer["id"]
                    ).status_code,
                    403,
                )
                admin("agent", login=agent_login, parent=other_login, role="个人推广员")
                pay(oid, payer="verified-gateway-id", payer_login=agent_login)
                self.assertEqual(inviter.get("/api/state").json["credits"], before)
                self.assertIn(oid, [r["id"] for r in promo(team)["orders"]])
                self.assertNotIn(oid, [r["id"] for r in promo(other)["orders"]])
                self.assertIn(login, [r["login"] for r in promo(other)["clients"]])
                self.assertNotIn(login, [r["login"] for r in promo(team)["clients"]])
                self.assertEqual(
                    post(
                        self.c, "admin/growth", action="settle", order=oid
                    ).status_code,
                    400,
                )
                admin("verify-payer", order=oid, reference="线下核对凭据")
                admin("settle", order=oid)
                with studio.db(True) as c:
                    commerce.refund(
                        c,
                        c.execute(
                            "SELECT * FROM purchase WHERE id=?", (oid,)
                        ).fetchone(),
                        "r-" + oid,
                    )
                admin("recover", order=oid, reference="到账凭据")
                self.assertEqual(
                    next(r for r in promo(team)["commissions"] if r["order_id"] == oid)[
                        "status"
                    ],
                    "recovered",
                )
                # Approving a channel claim must also check the invitation ancestry.
                admin("agent", login=login, role="个人推广员")
                code = promo(guest)["codes"]["agent"]
                post(inviter, "promotion/claim", code=code)
                pending = next(
                    r
                    for r in self.c.get("/api/admin/growth").json["reviews"]
                    if r["guest"] == owner_login
                )
                self.assertEqual(
                    post(
                        self.c,
                        "admin/growth",
                        action="approve-transfer",
                        id=pending["id"],
                    ).status_code,
                    400,
                )
        finally:
            admin("rules", **original)

    def test_growth_legacy_schema_migration(self):
        import sqlite3
        from server import growth

        with sqlite3.connect(":memory:") as c:
            c.row_factory = sqlite3.Row
            c.execute(
                "CREATE TABLE attribution(guest TEXT PRIMARY KEY,owner TEXT,kind TEXT,code TEXT,created TEXT)"
            )
            c.execute(
                "INSERT INTO attribution VALUES('g','m','merchant','legacy','2026-01-01')"
            )
            c.commit()
            growth.initialize(c)
            c.commit()
            growth.initialize(c)
            self.assertEqual(growth.attribution(c, "g"), {"merchant": "m"})
            c.execute("INSERT INTO channel_agent(tenant,kind) VALUES('a','个人推广员')")
            c.execute(
                "INSERT INTO attribution VALUES('g','a','agent','new','2026-11-23')"
            )
            self.assertEqual(growth.attribution(c, "g")["agent"], "a")

    def test_v3_imported_skill_and_model_fallback(self):
        from server import model, skill_library

        self.admin()
        rules = dict(
            id="custom_weekend_test",
            name="周末邀约",
            kind="poster",
            match=["周末邀约"],
            requires=["poster_design"],
            instructions=dict(
                copy="逐条核对条件。",
                image="在活动标题四周留白。",
                video="",
                qa="复核海报。",
            ),
            reason="首次验收",
        )
        self.assertEqual(
            post(
                self.c, "admin/skill-import", **{**rules, "requires": ["unknown"]}
            ).status_code,
            400,
        )
        self.assertEqual(post(self.c, "admin/skill-import", **rules).status_code, 200)

        def planned():
            with studio.db() as c:
                return skill_library.attach(
                    {"original": "夏季周末邀约"},
                    "poster",
                    overrides=skill_library.effective_versions(c, "trial"),
                )["skills"]

        self.assertNotIn(rules["id"], [r["id"] for r in planned()])
        self.assertEqual(
            post(
                self.c, "admin/skill-version", id=rules["id"], action="release", n=1
            ).status_code,
            200,
        )
        self.assertEqual(planned()[-1]["id"], rules["id"])
        for action, active in [("disable", False), ("enable", True)]:
            self.assertEqual(
                post(
                    self.c, "admin/skill-version", id="poster_design", action=action
                ).status_code,
                200,
            )
            self.assertEqual(rules["id"] in [r["id"] for r in planned()], active)
        self.assertEqual(
            post(
                self.c, "admin/skill-version", id=rules["id"], action="rollback", n=0
            ).status_code,
            200,
        )
        self.assertNotIn(rules["id"], [r["id"] for r in planned()])
        ids = ["custom-" + uuid.uuid4().hex for _ in range(2)]
        try:
            for i, platform in enumerate(ids):
                res = post(
                    self.c,
                    "admin/model-platform",
                    id=platform,
                    label="验收连接",
                    capability="text",
                    model="model-" + str(i),
                    url="https://fixture.invalid/chat",
                )
                self.assertEqual(res.status_code, 200)
            self.assertEqual(
                post(
                    self.c, "admin/model-routes", text=ids[0], backups={"text": ids[0]}
                ).status_code,
                400,
            )
            self.assertEqual(
                post(
                    self.c, "admin/model-routes", text=ids[0], backups={"text": ids[1]}
                ).status_code,
                200,
            )
            version = self.c.get("/api/admin").json["modelPlatforms"]["routeVersion"]
            self.assertEqual(
                post(
                    self.c, "admin/model-routes", text="", expectedVersion=version - 1
                ).status_code,
                400,
            )
            with studio.db() as c:
                saved = c.execute(
                    "SELECT after_json FROM model_route_version WHERE n=?", (version,)
                ).fetchone()
                self.assertEqual(
                    json.loads(saved[0])["text"]["backup"],
                    {"platform": ids[1], "model": "model-1"},
                )
            with patch.object(
                model, "chat_request", side_effect=[OSError(), {"ok": True}]
            ) as ask:
                self.assertEqual(model.ask("任务", {}), ({"ok": True}, "model-1"))
                self.assertEqual(
                    [r.args[0]["provider"] for r in ask.call_args_list], ids
                )
            with patch.dict(os.environ, {"TRUPIC_MODEL_STAGE": "production"}):
                self.assertFalse(model.route("text")["model"])
        finally:
            post(self.c, "admin/model-routes", text="", backups={"text": ""})

    def test_v3_video_reference_cuts_and_private_access(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "reference.mp4")
            subprocess.run(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=red:s=64x64:d=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=64x64:d=2",
                    "-filter_complex",
                    "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                    "-map",
                    "[v]",
                    "-c:v",
                    "libx264",
                    path,
                ],
                check=True,
            )
            with open(path, "rb") as stream:
                res = self.c.post(
                    "/api/video-references",
                    data={"video": (stream, "参考.mp4"), "authorized": "true"},
                )
        self.assertEqual(res.status_code, 200, res.json)
        self.assertEqual(res.json["cuts"], [2])
        payload = dict(
            brief="周末台球组局",
            deliveryMode="video",
            ratio="story",
            videoReference=res.json["id"],
        )
        self.assertEqual(
            post(studio.app.test_client(), "creations/plan", **payload).status_code, 404
        )
        q = post(self.c, "creations/plan", **payload).json
        spec = next(
            i["spec"]
            for i in studio.quotes.loads(q["quote"])["items"]
            if i["spec"]["kind"] == "video"
        )
        self.assertTrue(spec["plan"]["videoReference"]["authorized"])
        self.assertEqual(spec["replacement"]["storyboard"][1]["end"], 8)

    def test_v3_poster_region_preserves_pixels_and_task_margin(self):
        from PIL import ImageChops

        self.admin()
        q = post(
            self.c,
            "creations/plan",
            brief="周末台球组局",
            deliveryMode="image",
            ratio="square",
            imageCount=1,
        ).json
        with patch.object(studio.pool, "submit"):
            run = post(
                self.c,
                "creations",
                quote=q["quote"],
                confirmedCost=q["cost"],
                requestKey="base",
            ).json
            item = run["items"][-1]
            studio.produce(item["job"])
            work = "works/" + item["work"]
            v = self.c.get("/api/" + work).json["versions"][0]
            region = None
            for y in (0.02, 0.94, 0.2, 0.7):
                for x in (0.02, 0.94, 0.2, 0.7):
                    box = [x, y, x + 0.035, y + 0.035]
                    if not any(
                        x < b[2] and box[2] > b[0] and y < b[3] and box[3] > b[1]
                        for b in v["protectedAreas"]
                    ):
                        region = box
                        break
                if region:
                    break
            self.assertIsNotNone(region)
            quote = post(
                self.c,
                work + "/revision-quote",
                base=1,
                action="region",
                instruction="压暗",
                region=region,
            )
            self.assertEqual(quote.status_code, 200, quote.json)
            job = post(
                self.c,
                work + "/revise",
                quote=quote.json["quote"],
                confirmed=True,
                confirmedCost=1,
                requestKey="patch",
            ).json
            studio.produce(job["id"])
            state = self.c.get("/api/jobs/" + job["id"]).json
            self.assertEqual(state["state"], "complete", state)
        versions = self.c.get("/api/" + work).json["versions"]
        self.assertEqual(len(versions), 2)
        with (
            self.c.get(versions[1]["poster"]) as first,
            self.c.get(versions[0]["poster"]) as second,
        ):
            before = Image.open(io.BytesIO(first.data)).convert("RGB")
            after = Image.open(io.BytesIO(second.data)).convert("RGB")
        bounds = ImageChops.difference(before, after).getbbox()
        self.assertIsNotNone(bounds)
        selected = tuple(round(n * before.size[i % 2]) for i, n in enumerate(region))
        self.assertTrue(
            bounds[0] >= selected[0]
            and bounds[1] >= selected[1]
            and bounds[2] <= selected[2]
            and bounds[3] <= selected[3]
        )
        row = self.c.get("/api/admin/task-costs?job=" + job["id"]).json[0]
        self.assertIsNone(row["margin"])
        response = post(
            self.c, "admin/task-costs", job=job["id"], amount="0.12", source="测试账单"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.c.get("/api/admin/task-costs?job=" + job["id"]).json[0]["margin"],
            "-0.120000",
        )

    def test_v3_region_edit_protocol_uses_only_selected_patch(self):
        import base64
        from email import policy
        from email.parser import BytesParser
        from unittest.mock import Mock
        from server import region_edit

        crop = Image.new("RGB", (36, 24), "red")
        output = io.BytesIO()
        Image.new("RGB", crop.size, "blue").save(output, "PNG")
        response = json.dumps(
            {"data": [{"b64_json": base64.b64encode(output.getvalue()).decode()}]}
        ).encode()
        transport = Mock()
        transport.open.return_value = io.BytesIO(response)
        cfg = {
            "model": "fixture-edit",
            "provider": "fixture",
            "url": "https://model.invalid/edits",
        }
        with patch.object(
            region_edit.urllib.request, "build_opener", return_value=transport
        ):
            result = region_edit.cloud_patch(cfg, crop, "换成蓝色")
        self.assertEqual(result.getpixel((2, 2)), (0, 0, 255))
        request = transport.open.call_args.args[0]
        body = BytesParser(policy=policy.default).parsebytes(
            (
                "Content-Type: " + request.get_header("Content-type") + "\r\n\r\n"
            ).encode()
            + request.data
        )
        parts = {
            p.get_param("name", header="content-disposition"): p
            for p in body.iter_parts()
        }
        self.assertEqual(parts["prompt"].get_payload(decode=True).decode(), "换成蓝色")
        with Image.open(io.BytesIO(parts["image"].get_payload(decode=True))) as sent:
            self.assertEqual(sent.size, crop.size)
            self.assertEqual(sent.getpixel((2, 2)), (255, 0, 0))

    def test_v3_storage_outbox_and_download_scope(self):
        from server import object_storage
        from unittest.mock import Mock

        self.admin()
        run = submit_with_copy(self.c, "jobs", **self.plan())
        self.assertEqual(self.finish(run.json["id"])["state"], "complete")
        work = run.json["work"]
        path = f"/api/works/{work}/v/1/download"
        config = {
            "TRUPIC_COS_BUCKET": "test-000",
            "TRUPIC_COS_REGION": "test-region",
            "COS_SECRET_ID": "fixture",
            "COS_SECRET_KEY": "fixture",
        }
        fake = Mock()
        fake.get_presigned_download_url.return_value = "https://object.invalid/test"
        with (
            patch.dict(os.environ, config),
            patch.object(object_storage, "client", return_value=fake),
        ):
            with self.c.get(path) as local:
                self.assertEqual(local.status_code, 200)
            self.assertEqual(object_storage.drain(), 1)
            self.assertEqual(object_storage.drain(), 0)
            self.assertEqual(fake.upload_file.call_args.kwargs["ACL"], "private")
            self.assertEqual(self.c.get(path).location, "https://object.invalid/test")
            self.assertEqual(studio.app.test_client().get(path).status_code, 404)
            self.assertEqual(fake.get_presigned_download_url.call_count, 1)
            with self.c.get(path, headers={"X-Trupic-Native": "1"}) as local:
                self.assertEqual(local.mimetype, "image/png")

    def test_v3_private_work_feedback_and_support_reply(self):
        run = submit_with_copy(self.c, "jobs", **self.plan())
        self.assertEqual(self.finish(run.json["id"])["state"], "complete")
        work = run.json["work"]
        for _ in range(2):
            result = post(self.c, "complaints", work=work, message="请核对标题字号")
            self.assertEqual(result.status_code, 200, result.json)
            self.assertEqual(len(result.json), 1)
        complaint = result.json[0]["id"]
        support = studio.app.test_client()
        login = uuid.uuid4().hex
        post(support, "account/register", login=login, password="test-support")
        self.assertEqual(
            support.get("/api/complaints", query_string={"work": work}).status_code, 404
        )
        self.assertEqual(support.get("/api/admin/complaints").status_code, 403)
        self.admin()
        post(self.c, "admin/staff", login=login, role="support")
        self.assertEqual(support.get("/api/admin/complaints").status_code, 200)
        self.assertEqual(support.get("/api/admin/task-costs").status_code, 403)
        self.assertEqual(
            post(
                support, "admin/complaints", id=complaint, reply="字号已核对"
            ).status_code,
            200,
        )
        self.assertEqual(
            post(support, "admin/complaints", id=complaint, reply="覆盖").status_code,
            400,
        )
        self.assertEqual(
            self.c.get("/api/complaints", query_string={"work": work}).json[0]["reply"],
            "字号已核对",
        )

    def test_v3_capped_rollover_refund_and_quarter_visibility(self):
        from server import commerce, wallet

        self.admin()
        post(
            self.c,
            "account/register",
            login=uuid.uuid4().hex,
            password="merchant-fixture",
        )
        quarter = post(
            self.c,
            "admin/offers",
            cycle="quarter",
            name="季付储备",
            cents=3000,
            credits=12,
            bonus=0,
        ).json[0]
        self.assertNotIn(
            quarter["id"], [o["id"] for o in self.c.get("/api/shop").json["offers"]]
        )
        offer = post(
            self.c,
            "admin/offers",
            cycle="month",
            name="结转验收",
            cents=1000,
            credits=12,
            bonus=0,
            carry_cap=5,
        ).json[0]
        with patch.dict(
            os.environ,
            {
                "TRUPIC_CHECKOUT_URL": "https://pay.invalid",
                "TRUPIC_PAYMENT_SECRET": "test",
            },
        ):
            oid = post(
                self.c,
                "orders",
                offer=offer["id"],
                credits=12,
                bonus=0,
                cents=1000,
                requestKey="carry",
            ).json["id"]
        with studio.db(True) as c:
            row=c.execute("SELECT * FROM purchase WHERE id=?",(oid,)).fetchone()
            tenant=row["tenant"]
            commerce.fulfill(c,row,"receipt-"+oid)
            end=c.execute("SELECT ends FROM subscription WHERE order_id=?",(oid,)).fetchone()[0]
            with patch.object(wallet,"now",return_value=end):
                wallet.expire(c,tenant)
                wallet.expire(c,tenant)
            lots=c.execute("SELECT remaining FROM credit_lot WHERE tenant=? AND source='套餐积分结转'",(tenant,)).fetchall()
            self.assertEqual([r[0] for r in lots],[5])
            commerce.refund(c,c.execute("SELECT * FROM purchase WHERE id=?",(oid,)).fetchone(),"receipt-"+oid)
            self.assertEqual(c.execute("SELECT SUM(remaining) FROM credit_lot WHERE tenant=? AND ref LIKE ?",(tenant,oid+"%")).fetchone()[0],0)

    def test_v3_formal_model_release_gate(self):
        from server import model_tools as mt, providers
        self.admin()
        cfg=dict(id="custom-"+uuid.uuid4().hex,capability="text",label="fixture",url="https://model.invalid/v1/chat/completions",model="opaque-id",protocol="chat")
        post(self.c,"admin/model-platform",**cfg)
        with patch.object(mt.PROBES,"submit",side_effect=lambda fn,*args: fn(*args)), patch.object(mt.model,"chat_request",return_value={"ok":True}):
            probe=post(self.c,"admin/probes",**cfg).json["id"]
        meta=dict(**cfg,probe=probe,family="v3-test",version="2.10",minimum="2.2",released="2026-01-01",source="https://model.invalid/release",review="隔离测试记录")
        with patch.dict(os.environ,{"TRUPIC_MODEL_STAGE":"production"}):
            self.assertEqual(post(self.c,"admin/model-routes",text=cfg["id"]).status_code,400)
            for changes in (dict(released="2025-01-01"),dict(released=""),dict(minimum="2.11"),dict(probe="0"*32)):
                self.assertEqual(post(self.c,"admin/model-admission",**{**meta,**changes}).status_code,400)
            self.assertEqual(post(self.c,"admin/model-admission",**meta).status_code,200)
            self.assertEqual(post(self.c,"admin/model-routes",text=cfg["id"]).status_code,200)
            self.assertEqual(studio.model.route("text")["model"],"opaque-id")
            post(self.c,"admin/model-routes",text="local-rules")
        post(self.c,"admin/model-routes",text="")

    def test_v3_expiry_reserve_release_uses_same_lot(self):
        from server import wallet
        with self.c.session_transaction() as sess: tenant=sess["tenant"]
        with studio.db(True) as c:
            wallet.grant(c,tenant,"付费积分包","paid-"+tenant,20)
            wallet.reserve(c,tenant,"hold",5)
            c.execute("UPDATE credit_lot SET expires='2020-01-01' WHERE tenant=? AND source='开通工作室体验积分'",(tenant,))
            wallet.finish(c,tenant,"hold",False)
            wallet.finish(c,tenant,"hold",False)
            self.assertEqual(c.execute("SELECT credits FROM merchant WHERE id=?",(tenant,)).fetchone()[0],20)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM credit_event WHERE tenant=? AND action='release'",(tenant,)).fetchone()[0],1)

    def test_v3_export_all_advertised_durations(self):
        with self.c.session_transaction() as sess: tenant=sess["tenant"]
        with studio.db(True) as c:
            starts=studio.now()
            c.execute("INSERT INTO subscription VALUES(?,?,?,?,?,?)",(uuid.uuid4().hex,tenant,starts,studio.commerce.month_after(starts,1),1,100))
        for duration in (15,30,45):
            with self.subTest(duration=duration), patch.dict(os.environ,{"TRUPIC_VIDEO_RENDERER":"ffmpeg"}):
                q=post(self.c,"creations/plan",brief="给台球室做活动短片",facts="店里有大桌；可借球杆；提供巧粉；前台登记；可自带球杆；周五可预约",
                       deliveryMode="video",ratio="portrait",duration=duration).json
                with patch.object(studio.pool,"submit"):
                    row=post(self.c,"creations",quote=q["quote"],confirmedCost=q["cost"],requestKey=uuid.uuid4().hex).json
                    for item in row["items"]: studio.produce(item["job"])
                result=self.c.get("/api/creations/"+row["id"]).json
                self.assertTrue(result["complete"],[(i["state"],i["error"]) for i in result["items"]])
                video=result["items"][-1]
                folder=studio.DATA/tenant/"works"/video["work"]/"1"
                meta=json.loads(subprocess.check_output(["ffprobe","-v","error","-select_streams","v","-show_entries","stream=duration,nb_frames","-of","json",str(folder/"video.mp4")]))
                self.assertEqual(float(meta["streams"][0]["duration"]),duration)
                self.assertEqual(int(meta["streams"][0]["nb_frames"]),duration*24)
                with zipfile.ZipFile(folder/"edit.zip") as z:
                    shots=json.loads(z.read("timeline.json"))["shots"]
                    self.assertEqual(shots[-1]["endFrameExclusive"],duration*24)
                    self.assertEqual(len(shots),{15:3,30:5,45:7}[duration])
                    self.assertIn(f"00:00:{duration:02d},000",z.read("captions.srt").decode())

    def test_v3_reference_assets_and_scoped_edit(self):
        ids=[]
        for name in ("matcha","hotpot","retail"):
            with Image.open("server/scenes/"+name+".webp") as image:
                stream=io.BytesIO(); image.convert("RGB").save(stream,"PNG"); stream.seek(0)
                with patch.dict(os.environ,{"TRUPIC_CUTOUT":"/missing"}):
                    ids.append(self.c.post("/api/assets",data={"image":(stream,name+".png")}).json["id"])
        proposal=post(self.c,"assets/suggest-sources",ids=ids,brief="周末上新",authorized=True)
        self.assertEqual(proposal.status_code,200,proposal.json)
        self.assertEqual({proposal.json["asset"],*(r["id"] for r in proposal.json["references"])},set(ids))
        self.assertEqual(post(studio.app.test_client(),"assets/suggest-sources",ids=ids,authorized=True).status_code,404)
        refs=[dict(id=ids[1],role="color",authorized=True),dict(id=ids[2],role="layout",authorized=True)]
        payload=dict(brief="抹茶饮品周末到店尝鲜",facts="抹茶拿铁48元；仅限周末",deliveryMode="image",ratio="portrait",imageCount=1,
                     asset=ids[0],assetConfirmed=True,assetMode="original",references=refs)
        self.assertEqual(post(self.c,"creations/plan",**{**payload,"references":[{**refs[0],"authorized":False}]}).status_code,400)
        q=post(self.c,"creations/plan",**payload).json
        with patch.object(studio.pool,"submit"):
            run=post(self.c,"creations",quote=q["quote"],confirmedCost=q["cost"],requestKey="reference").json
            for item in run["items"]: studio.produce(item["job"])
        work="works/"+run["items"][-1]["work"]
        v=self.c.get("/api/"+work).json["versions"][0]
        self.assertEqual(v["asset"],ids[0])
        self.assertEqual(v["plan"]["posterArt"]["composition"],"photo-grid")
        self.assertEqual([r["id"] for r in v["plan"]["references"]],ids[1:])
        self.assertEqual(self.c.delete("/api/assets/"+ids[2]).status_code,400)
        revision=post(self.c,work+"/revision-quote",base=1,action="edit",instruction="48元改成38元；标题改为周末来一杯").json
        self.assertEqual(revision["cost"],1)
        self.assertIn("38元",revision["changes"]["body"])
        with patch.object(studio.pool,"submit"):
            job=post(self.c,work+"/revise",quote=revision["quote"],confirmed=True,confirmedCost=1,requestKey="edit").json
            studio.produce(job["id"])
        latest=self.c.get("/api/"+work).json["versions"]
        self.assertEqual(len(latest),2)
        self.assertEqual(latest[0]["title"],"周末来一杯")
        self.assertIn("38元",latest[0]["body"])
        self.assertIn("48元",latest[1]["body"])

    def test_home_brief_without_photo_revision_and_adoption(self):
        q = post(self.c, "creations/plan", brief="帮我宣传台球室").json
        self.assertTrue(q["ready"], q)
        self.assertEqual(q["cost"], 4)
        topic = self.state()["recs"][0]
        q = post(self.c, "creations/plan", brief=topic["brief"], topicId=topic["topicId"]).json
        run = submit_with_copy(self.c, "creations", confirmedCost=q["cost"], quote=q["quote"], requestKey=uuid.uuid4().hex).json
        for item in run["items"]:
            self.assertEqual(self.finish(item["job"])["state"], "complete")
        poster = run["items"][1]["work"]
        initial = self.c.get("/api/works/" + poster).json["versions"][0]
        self.assertEqual(initial["plan"]["topic"]["id"], topic["topicId"])
        self.assertNotIn("商品规格", initial["cta"])
        for action in ("revision", "layout", "redesign"):
            result = submit_revision(self.c, "works/" + poster + "/revise", base=1, action=action, requestKey=uuid.uuid4().hex)
            done = self.finish(result.json["id"])
            self.assertEqual(done["state"], "complete", done)
            latest = self.c.get("/api/works/" + poster).json["versions"][0]
            if action == "revision":
                self.assertEqual(latest["title"], initial["suggestion"]["title"])
            if action == "layout":
                self.assertEqual(latest["body"], initial["body"])
        self.assertTrue(next(r for r in self.state()["recs"] if r["topicId"] == topic["topicId"])["adopted"])
        with self.c.get(run["download"]) as downloaded:
            self.assertEqual(downloaded.status_code, 200)
        with studio.db() as c:
            self.assertTrue(all(c.execute("SELECT count FROM downloads WHERE work=?", (i["work"],)).fetchone()[0] == 1 for i in run["items"]))
        self.assertEqual(self.state()["credits"], 113)

    def test_dense_poster_can_apply_layout_without_losing_original_or_copy(self):
        brief = "给台球室做一张满屏字海报，约朋友下班组局。"
        quote = post(self.c, "creations/plan", brief=brief).json
        run = submit_with_copy(self.c, "creations", quote=quote["quote"], confirmedCost=quote["cost"], requestKey=uuid.uuid4().hex).json
        poster = next(item for item in run["items"] if item["role"] == "poster")
        self.assertEqual(self.finish(poster["job"])["state"], "complete")
        url = "works/" + poster["work"]
        version = self.c.get("/api/" + url).json["versions"][0]
        with self.c.get(version["poster"]) as response:
            before = response.data
        revision = submit_revision(self.c, url + "/revise", base=1, action="layout", requestKey=uuid.uuid4().hex).json
        self.assertEqual(self.finish(revision["id"])["state"], "complete")
        latest, original = self.c.get("/api/" + url).json["versions"]
        self.assertEqual((latest["title"], latest["body"]), (original["title"], original["body"]))
        with self.c.get(latest["poster"]) as response:
            self.assertNotEqual(response.data, before)
        self.assertEqual(post(self.c, url + "/restore/1").status_code, 200)

    def test_home_hotpot_copy_addresses_first_visit_and_return_visit(self):
        def draft(brief):
            plan = post(self.c, "creations/plan", brief=brief).json
            return studio.quotes.loads(plan["quote"])["items"][0]["spec"]["replacement"]
        new = draft("给首次到店的顾客写一份菌菇火锅推广文案")
        returning = draft("给回头客写一份菌菇火锅邀约文案")
        self.assertIn("喜欢的口味", new["body"])
        self.assertIn("上回", returning["body"])
        self.assertNotEqual(new["title"], returning["title"])

    def test_home_fidelity_uses_merchant_region_and_preflight_before_jobs(self):
        bundle, _ = self.bundle_plan(cutout=True)
        asset = studio.quotes.loads(bundle["quote"])["specs"][0]["asset"]
        req = dict(brief="做一张抹茶海报，保留包装文字", asset=asset)
        self.assertFalse(post(self.c, "creations/plan", **req).json["ready"])
        self.assertFalse(post(self.c, "creations/plan", **req, assetConfirmed=True).json["ready"])
        region = [0.2,0.2,0.8,0.8]
        q = post(self.c, "creations/plan", **req, assetConfirmed=True, identityRegion=region).json
        self.assertTrue(q["ready"],q)
        self.assertEqual(studio.quotes.loads(q["quote"])["items"][-1]["spec"]["identityRegion"],region)
        with patch.object(studio,"preflight",side_effect=ValueError("关键标识已遮挡")):
            response = submit_with_copy(self.c,"creations",quote=q["quote"],confirmedCost=q["cost"],requestKey=uuid.uuid4().hex)
        self.assertEqual(response.status_code,400)
        self.assertFalse(self.state()["jobs"])
        self.assertEqual(self.state()["credits"],120)

    def test_hk_handshake_retry_only_for_the_official_feed_and_active_http_proxy(self):
        import ssl
        import urllib.error
        from server import event_sources as feeds

        with (
            patch("urllib.request.build_opener") as opener,
            patch("urllib.request.getproxies", return_value={"https": "http://localhost:8080"}),
            patch("urllib.request.proxy_bypass", return_value=False) as bypass,
            patch.object(feeds, "read_hk_via_resolved_proxy", return_value=b'{"vcalendar": []}') as retry,
        ):
            opener.return_value.open.side_effect = urllib.error.URLError(ssl.SSLEOFError("EOF"))
            self.assertEqual(feeds.read_calendar(feeds.HK_URL), {"vcalendar": []})
            self.assertEqual(retry.call_args.args[0].port, 8080)
            retry.reset_mock()
            with self.assertRaises(urllib.error.URLError):
                feeds.read_calendar(feeds.APPLE_NEWS)
            bypass.return_value = True
            with self.assertRaises(urllib.error.URLError):
                feeds.read_calendar(feeds.HK_URL)
            bypass.return_value = False
            opener.return_value.open.side_effect = urllib.error.URLError(ssl.SSLCertVerificationError("certificate"))
            with self.assertRaises(urllib.error.URLError):
                feeds.read_calendar(feeds.HK_URL)
            opener.return_value.open.side_effect = urllib.error.HTTPError(feeds.HK_URL, 403, "Forbidden", {}, None)
            with self.assertRaises(urllib.error.HTTPError):
                feeds.read_calendar(feeds.HK_URL)
            retry.assert_not_called()

    def test_hk_proxy_connects_by_public_address_and_verifies_official_hostname(self):
        from urllib.parse import urlsplit
        from server import event_sources as feeds

        with (
            patch("urllib.request.urlopen") as dns,
            patch("http.client.HTTPConnection") as connection,
            patch("ssl.create_default_context") as tls,
        ):
            dns_body = dns.return_value.__enter__.return_value.read
            records = [{"type": 1, "data": "127.0.0.1"}, {"type": 1, "data": "45.119.93.185"}]
            dns_body.return_value = json.dumps({"Status": 0, "Answer": records}).encode()
            conn = connection.return_value
            response = conn.getresponse.return_value.__enter__.return_value
            response.status, response.read.return_value = 200, b"calendar"
            proxy = urlsplit("http://localhost:1082")
            self.assertEqual(feeds.read_hk_via_resolved_proxy(proxy), b"calendar")
            conn.set_tunnel.assert_called_once_with("45.119.93.185", 443, headers={})
            self.assertEqual(tls.return_value.wrap_socket.call_args.kwargs["server_hostname"], "www.1823.gov.hk")
            self.assertEqual(conn.request.call_args.kwargs["headers"]["Host"], "www.1823.gov.hk")
            response.read.assert_called_once_with(2_000_001)
            response.status = 302
            with self.assertRaisesRegex(ValueError, "HTTP 302"):
                feeds.read_hk_via_resolved_proxy(proxy)
            dns_body.return_value = json.dumps({"Status": 0, "Answer": records[:1]}).encode()
            with self.assertRaisesRegex(ValueError, "公网地址"):
                feeds.read_hk_via_resolved_proxy(proxy)

    def test_event_discovery_filters_refreshes_and_withdraws(self):
        from server import event_sources
        self.admin()
        city = "杭州" + uuid.uuid4().hex[:4]
        post(self.c,"profile",name="澄月",city=city,industry="餐饮火锅")
        source = dict(name="主办方活动", category="公开热点",url="https://example.org/"+uuid.uuid4().hex,
                      city=city,keywords="餐饮",verified=True)
        sid = post(self.c, "admin/event-feed", **source).json["id"]
        today = dt.date.today().isoformat()
        event = {"@type":"Event", "@id":"one", "name":"餐饮交流会", "startDate":today, "endDate":today,
                 "url":"https://example.org/food", "location":{"address":{"addressLocality":city}}}
        with patch.object(event_sources,"read_calendar",return_value=[event]):
            self.assertEqual(post(self.c,"admin/event-sync",id=sid).json["count"],1)
            self.assertEqual(post(self.c,"admin/event-sync",id=sid).json["count"],1)
        topic = self.state()["recs"][0]
        self.assertEqual(topic["title"], event["name"])
        self.assertEqual(topic["source"], event["url"])
        outsider = studio.app.test_client()
        outsider.get("/api/state")
        post(outsider,"profile",name="书店",industry="图书",city=city)
        self.assertNotIn(event["name"], [r["title"] for r in outsider.get("/api/topics").json])
        q = post(self.c,"creations/plan",brief=topic["brief"],topicId=topic["topicId"]).json
        with patch.object(event_sources,"read_calendar",side_effect=OSError()):
            self.assertEqual(post(self.c,"admin/event-sync",id=sid).status_code,400)
        self.assertEqual(self.state()["recs"][0]["topicId"],topic["topicId"])
        with patch.object(event_sources,"read_calendar",return_value=[{**event,"eventStatus":"EventCancelled"}]):
            self.assertEqual(post(self.c,"admin/event-sync",id=sid).json["count"],0)
        self.assertNotIn(event["name"],[r["title"] for r in self.state()["recs"]])
        self.assertEqual(submit_with_copy(self.c,"creations",quote=q["quote"],confirmedCost=q["cost"],requestKey=uuid.uuid4().hex).status_code,400)
        self.assertEqual(post(self.c,"creations/plan",brief=topic["brief"],topicId=topic["topicId"]).status_code,400)
        self.assertEqual(post(outsider,"admin/event-sync",id=sid).status_code,403)
        self.assertEqual(self.state()["credits"],120)

    def test_skill_revisions_are_tested_scoped_and_reversible(self):
        from server.skill_library import BY_ID, effective_versions
        from server.creative import uidnum
        self.admin()
        skill = "poster_design"
        method = {**BY_ID[skill]["instructions"], "image":"让标题与商品之间留一个字宽。"}
        def change(action, **more):
            return post(self.c,"admin/skill-version",id=skill,action=action,**more)
        def revisions():
            return next(s for s in self.c.get("/api/admin").json["skills"] if s["id"]==skill)["versions"]
        self.assertEqual(change("test",instructions=method,reason="核对标题留白").status_code,200)
        n = revisions()[0]["n"]
        try:
            change("pilot",n=n)
            with studio.db() as c:
                for pilot in (True,False):
                    tenant = next(str(i) for i in range(300) if (uidnum(str(i))%100<10) == pilot)
                    self.assertEqual(skill in effective_versions(c,tenant),pilot)
            change("release",n=n)
            req = dict(brief="为台球室做海报")
            q = post(self.c,"creations/plan",**req).json
            saved = studio.quotes.loads(q["quote"])["items"][-1]["spec"]["plan"]
            self.assertIn(method["image"],saved["promptBrief"]["prompts"]["image"])
            self.assertEqual(change("rollback",n=0).status_code,200)
            again = post(self.c,"creations/plan",**req).json
            self.assertNotIn(method["image"],studio.quotes.loads(again["quote"])["items"][-1]["spec"]["plan"]["promptBrief"]["prompts"]["image"])
            change("test",instructions={**method,"copy":"编造优惠价格"},reason="固定测试")
            failed = revisions()[0]
            self.assertEqual(failed["status"],"failed")
            self.assertEqual(change("release",n=failed["n"]).status_code,400)
        finally:
            change("rollback",n=0)

    def test_provider_money_budget_and_sourced_bill(self):
        self.admin()
        with patch.dict(os.environ,{"TRUPIC_DAILY_BUDGET_CNY":"0.25","TRUPIC_VIDEO_RESERVE_CNY":"0.2"}):
            studio.model.reserve_provider_call("video")
            with self.assertRaisesRegex(ValueError,"金额预算"):
                studio.model.reserve_provider_call("video")
            self.assertEqual(self.c.get("/api/admin").json["modelCosts"]["reserved"],0.2)
        bill = dict(platform="billing-fixture",model="video",kind="video",day=studio.now()[:10],source="核对账单",amount="0.180003",currency="CNY")
        for _ in range(2):
            self.assertEqual(post(self.c,"admin/provider-bill",**bill).status_code,200)
        rows = [r for r in self.c.get("/api/admin").json["modelCosts"]["bills"] if r["platform"]=="billing-fixture"]
        self.assertEqual([r["amount"] for r in rows],["0.180003"])
        self.assertEqual(post(self.c,"admin/provider-bill",**{**bill,"amount":"nan"}).status_code,400)
        self.assertEqual(self.state()["credits"],120)

    def test_atlas_and_dashscope_task_protocols(self):
        from server import video_api as video
        self.admin()
        for platform,protocol,submitted,completed,poll in [
            ("atlas","atlas-video",{"data":{"id":"abc"}},{"data":{"status":"completed","outputs":["https://cdn.example/clip.mp4"]}},"/api/v1/model/prediction/abc"),
            ("bailian","dashscope-video",{"output":{"task_id":"abc"}},{"output":{"task_status":"SUCCEEDED","video_url":"https://cdn.example/clip.mp4"}},"/api/v1/tasks/abc")]:
            config = next(p for p in self.c.get("/api/admin").json["modelPlatforms"]["platforms"] if p["id"]==platform)["connections"]["video"]
            self.assertEqual(config["protocol"],protocol)
            config.update(key="test",model="wan2.7-t2v")
            with patch.object(video,"request_json",side_effect=[submitted,completed]) as remote:
                self.assertEqual(video.submit(config,"test","9:16"),"abc")
                self.assertEqual(video.poll_task(config,"abc")[1],"https://cdn.example/clip.mp4")
                self.assertTrue(remote.call_args.args[1].endswith(poll))
                payload = remote.call_args_list[0].args[2]
                self.assertEqual(payload.get("prompt") or payload["input"]["prompt"],"test")

    def test_publisher_news_dates_scoping_and_expiry(self):
        from xml.etree import ElementTree as ET
        from server import event_sources
        self.admin()
        today = dt.date.today()
        with studio.db() as c:
            feed = c.execute("SELECT * FROM event_feed WHERE id='apple-developer'").fetchone()
        def item(slug, date, link):
            return f"<entry><title>{slug}</title><published>{date}T10:00:00+08:00</published><link href='{link}'/></entry>"
        publisher = "https://developer.apple.com/news/"
        atom = ET.fromstring("<feed xmlns='http://www.w3.org/2005/Atom'>" +
                             item("近期公告", today, publisher+"a") +
                             item("过期公告", today-dt.timedelta(days=8), publisher+"b") +
                             item("外部转载", today, "https://elsewhere.example/x") + "</feed>")
        with patch.object(event_sources,"read_calendar",return_value=atom):
            self.assertEqual(post(self.c,"admin/event-sync",id=feed["id"]).json["count"],2)
        post(self.c,"profile",name="课程工作室",industry="编程培训",city="上海")
        first = self.state()["recs"][0]
        self.assertEqual(first["title"],"近期公告")
        self.assertIn("发布",first["brief"])
        self.assertNotIn("举行",first["brief"])
        with studio.db(True) as c:
            c.execute("UPDATE event_feed SET checked=datetime('now','-3 days') WHERE id=?", (feed["id"],))
        self.assertNotIn(first["title"],[r["title"] for r in self.state()["recs"]])

    def test_cross_industry_intent_only_uses_approved_methods(self):
        from server.governance import retrieve_method
        method_id = uuid.uuid4().hex
        with studio.db(True) as c:
            c.execute("""INSERT INTO cases(id,title,kind,category,status,tags,scenario,lesson)
                         VALUES(?, '饮品试饮邀请','视频','创意方法','approved','新客','午休','先提问，再展示选择。')""",(method_id,))
            c.execute("""INSERT INTO rules(id,case_id,method,retrievable) VALUES(?,?,'question',1)""",(method_id,method_id))
            for brief in ("火锅店首次到店怎么点菜", "台球室第一次来怎么组局", "午间书店海报"):
                self.assertEqual(retrieve_method(c,brief,{})["id"],method_id)
            c.execute("UPDATE cases SET status='pending' WHERE id=?", (method_id,))
            self.assertIsNone(retrieve_method(c,"给首次到店的顾客做一张展览海报",{}))
            c.execute("DELETE FROM rules WHERE id=?", (method_id,))
            c.execute("DELETE FROM cases WHERE id=?", (method_id,))

    def test_malformed_model_content_is_distinct_from_connection_failure(self):
        from server import model

        quote = post(self.c, "creations/plan", brief="给台球室写一条邀约文案").json
        plan = studio.quotes.loads(quote["quote"])["items"][0]["spec"]["plan"]
        with patch.object(model, "engine_name", return_value="test-model"):
            with patch.object(model, "ask", side_effect=lambda *args: model.response_object("无效格式")):
                self.assertEqual(generate_copy(plan)["reviewFlag"], "模型回复格式异常")
            with patch.object(model, "ask", side_effect=TimeoutError()):
                self.assertEqual(generate_copy(plan)["reviewFlag"], "模型调用未完成")

    def test_rejected_shared_draft_uses_checked_fallback_and_records_model(self):
        from server import providers
        platform = 'custom-' + uuid.uuid4().hex
        try:
            with studio.db(True) as c:
                providers.save(c,"test",dict(id=platform,label="固定模型",capability="text",model="text-proof",url="https://example.org/chat"))
                providers.select(c,"test",dict(text=platform))
            q = post(self.c,"creations/plan",brief="给台球室写一条邀约文案").json
            rejected = dict(title="虚构的标题",reviewFlag="模型草稿复核未通过")
            with patch("server.auto_pipeline.generate_copy",return_value=rejected):
                run = submit_with_copy(self.c,"creations",quote=q["quote"],confirmedCost=q["cost"],requestKey=uuid.uuid4().hex).json
                done = self.finish(run["items"][0]["job"])
            self.assertEqual(done["state"],"complete",done)
            work = self.c.get("/api/works/"+done["work"]).json["versions"][0]
            self.assertEqual(work["engine"],"本地创意规则")
            self.assertNotEqual(work["title"],rejected["title"])
            self.assertTrue(any(q["label"]=="待抽查" and "text-proof" in q["detail"] for q in work["quality"]))
        finally:
            with studio.db(True) as c:
                c.execute("DELETE FROM model_route WHERE platform=?",(platform,))
                c.execute("DELETE FROM model_provider WHERE id=?",(platform,))

    def test_reference_sources_cannot_overwrite_model_configuration(self):
        from pathlib import Path
        from server import model
        self.assertEqual(post(self.c,'admin/reference-settings',feed='').status_code,403)
        self.admin()
        with tempfile.TemporaryDirectory() as directory, patch.object(model,'SETTINGS',Path(directory)/'integrations.json'):
            original=model.settings() | dict(url='https://text.example/v1/chat/completions',model='legacy-text',key='keep-text-secret',imageUrl='https://image.example/v1/images/generations',imageModel='legacy-image',imageKey='keep-image-secret',visionModel='legacy-vision',visionUrl='https://vision.example/v1/chat/completions',visionKey='keep-vision-secret')
            model.save_settings(original)
            with studio.db() as c:
                routes_before=[tuple(r) for r in c.execute('SELECT * FROM model_route')]
            response=post(self.c,'admin/reference-settings',feed='https://references.example/feed.xml',license='已获授权',url='',model='',key='replacement',imageUrl='',imageModel='',visionModel='')
            self.assertEqual(response.status_code,200,response.json)
            saved=model.settings()
            for key in ('url','model','key','imageUrl','imageModel','imageKey','visionUrl','visionModel','visionKey'):
                self.assertEqual(saved[key],original[key])
            self.assertEqual(saved['feed'],'https://references.example/feed.xml')
            self.assertEqual(post(self.c,'admin/reference-settings',feed='http://insecure.example/feed').status_code,400)
            self.assertEqual(model.settings()['feed'],saved['feed'])
            with studio.db() as c:
                self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM model_route')],routes_before)
            admin=self.c.get('/api/admin')
            self.assertEqual(admin.json['modelPlatforms']['defaults']['image']['model'],'legacy-image')
            for key in ('keep-text-secret','keep-image-secret','keep-vision-secret'):
                self.assertNotIn(key,admin.text)

    def test_four_independent_capabilities_and_secret_retention(self):
        from server import model, providers
        self.admin()
        platform = 'custom-' + uuid.uuid4().hex
        try:
            for kind in providers.KINDS:
                payload = dict(id=platform,label='独立连接测试',capability=kind,url=f'https://{kind}.example/v1/chat/completions',model='fixture-'+kind,key='private-'+kind,protocol=providers.PROTOCOLS[kind][0])
                self.assertEqual(post(self.c,'admin/model-platform',**payload).status_code,200)
                self.assertEqual(post(self.c,'admin/model-platform',**{**payload,'key':''}).status_code,200)
            self.assertEqual(post(self.c,'admin/model-routes',**dict.fromkeys(providers.KINDS,platform)).status_code,200)
            for kind in providers.KINDS:
                self.assertEqual(model.route(kind)['key'],'private-'+kind)
                self.assertEqual(model.route(kind)['url'],f'https://{kind}.example/v1/chat/completions')
                self.assertNotIn('private-'+kind,self.c.get('/api/admin').text)
            self.assertEqual(post(self.c,'admin/model-platform',**{**payload,'url':'https://changed.example/v1/tasks','key':''}).status_code,400)
            self.assertEqual(post(self.c,'admin/model-platform',id='deepseek',capability='image',url='https://example.com/images/generations',model='deepseek-chat').status_code,400)
            self.assertEqual(post(self.c,'admin/model-platform',**{**payload,'capability':'image','protocol':'images','model':'deepseek-chat'}).status_code,400)
            post(self.c,'admin/model-routes',**dict.fromkeys(providers.KINDS,'local-rules'))
            self.assertTrue(all(model.route(k)['model']=='' for k in providers.KINDS))
        finally:
            with studio.db(True) as c:
                c.execute('DELETE FROM model_route')
                c.execute('DELETE FROM model_provider WHERE id=?',(platform,))

    def test_live_model_catalog_pagination_capabilities_and_failed_sync(self):
        from server import model_tools as mt
        from urllib.error import HTTPError
        self.admin()
        payload = dict(id='custom-'+uuid.uuid4().hex,capability='image',url='https://catalog.example/v1/images/generations',key='catalog-private',model='')
        self.assertEqual(post(studio.app.test_client(),'admin/sync-models',**payload).status_code,403)
        replies = [dict(data=[dict(id='text-only',domain='LLM'),dict(id='image-model',modalities=dict(input_modalities=['text'],output_modalities=['image']))],has_more=True,last_id='image-model'),dict(data=[dict(id='manual-model')],has_more=False)]
        with patch.object(mt,'request_json',side_effect=replies) as remote:
            response = post(self.c,'admin/sync-models',**payload)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(remote.call_args_list[1].args[1],'https://catalog.example/v1/models?after=image-model')
        self.assertEqual(remote.call_args.args[0]['key'],'catalog-private')
        rows = {r['id']:r for r in response.json['models']}
        self.assertEqual(rows['text-only']['kinds'],['text'])
        self.assertEqual(rows['image-model']['kinds'],['image'])
        self.assertFalse(rows['manual-model']['known'])
        self.assertNotIn('catalog-private',response.text)
        with patch.object(mt,'request_json',side_effect=HTTPError(payload['url'],403,'denied',{},None)):
            self.assertEqual(post(self.c,'admin/sync-models',**payload).status_code,400)
        with studio.db() as c:
            self.assertEqual(len(json.loads(c.execute('SELECT data FROM model_catalog WHERE platform=?',(payload['id'],)).fetchone()[0])),3)
        with patch.object(mt,'request_json') as remote:
            self.assertEqual(post(self.c,'admin/sync-models',**{**payload,'modelsUrl':'https://elsewhere.example/models'}).status_code,400)
            remote.assert_not_called()
        with patch.object(mt,'request_json',side_effect=[dict(output=dict(total=2,models=[dict(model='qwen-text',capabilities=['TG'])])),dict(output=dict(total=2,models=[dict(model='qwen-vision',capabilities=['TG','VU'])]))]) as remote:
            result = mt.sync_models('text',dict(provider='custom',url='https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/chat/completions',key='',model=''))
        self.assertEqual(result['models'][1]['kinds'],['text','vision'])
        self.assertIn('page_no=2',remote.call_args.args[1])

    def test_capability_probes_validate_actual_outputs_and_authentication(self):
        import base64
        from server import model_tools as mt
        self.admin()
        payload = dict(id='custom-'+uuid.uuid4().hex,capability='text',url='https://probe.example/v1/chat/completions',model='probe-text',key='probe-private')
        def inline(fn,*args): fn(*args)
        with patch.object(mt.PROBES,'submit',side_effect=inline), patch.object(mt.model,'chat_request',return_value=dict(ok=True)) as request:
            created = post(self.c,'admin/probes',**payload).json
        result = self.c.get('/api/admin/probes/'+created['id'])
        self.assertEqual(result.json['state'],'complete',result.json)
        self.assertEqual(request.call_args.args[0]['key'],'probe-private')
        self.assertNotIn('probe-private',result.text)
        self.assertNotIn('signature',result.json)
        self.assertEqual(studio.app.test_client().get('/api/admin/probes/'+created['id']).status_code,403)
        with patch.object(mt.PROBES,'submit',side_effect=inline), patch.object(mt.model,'chat_request',return_value=dict(color='wrong')):
            created = post(self.c,'admin/probes',**{**payload,'capability':'vision'}).json
        failed = self.c.get('/api/admin/probes/'+created['id']).json
        self.assertEqual(failed['state'],'failed')
        def recognize(cfg,name,messages,*args):
            raw=messages[0]['content'][1]['image_url']['url'].split(',')[1]
            pixel=Image.open(io.BytesIO(base64.b64decode(raw))).getpixel((20,20))
            colors={'red':(255,0,0),'green':(0,128,0),'blue':(0,0,255),'yellow':(255,255,0)}
            return dict(color=min(colors,key=lambda color:sum((a-b)**2 for a,b in zip(pixel,colors[color]))))
        with patch.object(mt.PROBES,'submit',side_effect=inline), patch.object(mt.model,'chat_request',side_effect=recognize):
            self.assertEqual(post(self.c,'admin/probes/'+created['id']+'/retry',**{**payload,'capability':'vision'}).status_code,200)
        self.assertEqual(self.c.get('/api/admin/probes/'+created['id']).json['state'],'complete')
        image = io.BytesIO();Image.new('RGB',(512,512),'green').save(image,format='PNG')
        with patch.object(mt.PROBES,'submit',side_effect=inline), patch.object(mt,'request_json',return_value=dict(data=[dict(b64_json=base64.b64encode(image.getvalue()).decode())])):
            created=post(self.c,'admin/probes',**{**payload,'capability':'image','url':'https://probe.example/v1/images/generations'}).json
        result=self.c.get('/api/admin/probes/'+created['id']).json
        self.assertEqual(result['state'],'complete',result)
        with self.c.get(result['preview']) as media:
            self.assertEqual(media.mimetype,'image/png')
        self.assertEqual(studio.app.test_client().get(result['preview']).status_code,403)

    def test_cloud_video_task_resume_and_actual_decoding(self):
        import shutil
        from pathlib import Path
        from server import video_api as video
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'fixture.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x320:rate=24','-t','1','-pix_fmt','yuv420p',str(source)],check=True)
            cfg=dict(provider='custom',url='https://video.example/tasks',model='fixture-video',key='video-private',protocol='ark-video')
            plan=dict(output=dict(width=320,height=320),coordination=dict(product='茶饮',concept='测试'))
            folder=root/'probe'
            with patch.dict(os.environ,{'TRUPIC_DAILY_VIDEO_CALLS':'0'}):
                with self.assertRaisesRegex(ValueError,'上限'):
                    video.prepare_background(folder,plan,dict(storyboard=[]),cfg)
            self.assertFalse((folder/'video-task.json').exists())
            with patch.object(video,'request_json',side_effect=[dict(id='task-1')]+[dict(status='running')]*120) as remote, patch.object(video.time,'sleep'):
                with self.assertRaisesRegex(ValueError,'同一任务'):
                    video.prepare_background(folder,plan,dict(storyboard=[]),cfg)
            self.assertEqual(sum(len(c.args)>2 for c in remote.call_args_list),1)
            with patch.object(video,'request_json',return_value=dict(status='succeeded',content=dict(video_url='https://cdn.example/video.mp4'))) as remote, patch.object(video,'download',side_effect=lambda url,dest:shutil.copy(source,dest)):
                frames=video.prepare_background(folder,plan,dict(storyboard=[]),cfg)
            self.assertEqual(len(list(frames.glob('*.jpg'))),216)
            self.assertEqual(remote.call_count,1)
            self.assertEqual(remote.call_args.args[1],cfg['url']+'/task-1')
            self.assertNotIn('video-private',(folder/'video-task.json').read_text())

    def test_auto_creation_uses_shared_text_and_selected_image_service(self):
        import base64
        from server import providers, model
        self.admin()
        q,_=self.bundle_plan()
        asset=studio.quotes.loads(q['quote'])['specs'][0]['asset']
        q=post(self.c,'creations/plan',asset=asset,brief='抹茶新品上新组图，48元/罐').json
        text_id,image_id=('custom-'+uuid.uuid4().hex for _ in range(2))
        try:
            with studio.db(True) as c:
                for kind,platform in [('text',text_id),('image',image_id)]:
                    providers.save(c,'test',dict(id=platform,label=kind,capability=kind,url=f'https://{kind}.example/v1/'+('chat/completions' if kind=='text' else 'images/generations'),model='fixture-'+kind,key='private-'+kind))
                providers.select(c,'test',dict(text=text_id,image=image_id,vision='local-rules',video='local-rules'))
            stream=io.BytesIO();Image.new('RGB',(720,720),'#aabb99').save(stream,format='PNG')
            def remote(request,timeout):
                payload=json.loads(request.data)
                self.assertEqual(request.get_header('Authorization'),'Bearer private-image')
                self.assertEqual(payload['model'],'fixture-image')
                return io.BytesIO(json.dumps(dict(data=[dict(b64_json=base64.b64encode(stream.getvalue()).decode())])).encode())
            draft=dict(title='一口清新',body='抹茶饮品，48元/罐',cta='试试这杯',engine='fixture-text',review={})
            reference = studio.quotes.loads(q["quote"])["items"][0]["spec"]["replacement"]
            with patch("server.copy_choices.write_options", return_value=[{**reference, **draft}, reference]):
                chosen = post(self.c, "copy-options", quote=q["quote"]).json["options"][0]["token"]
            with patch('server.auto_pipeline.generate_copy',side_effect=AssertionError("selected copy must be reused")) as text_call, patch('urllib.request.urlopen',side_effect=remote) as images:
                response=post(self.c,'creations',copyChoice=chosen,quote=q['quote'],confirmedCost=q['cost'],requestKey=uuid.uuid4().hex)
                self.assertEqual(response.status_code,200,response.json)
                group=response.json
                for item in group['items']:
                    finished=self.finish(item['job'])
                    self.assertEqual(finished['state'],'complete',finished)
            text_call.assert_not_called()
            self.assertEqual(images.call_count,3)
            result=self.c.get('/api/creations/'+group['id']).json
            self.assertEqual(result['title'],'一口清新')
        finally:
            with studio.db(True) as c:
                c.execute('DELETE FROM model_route')
                c.execute('DELETE FROM model_provider WHERE id IN (?,?)',(text_id,image_id))

    def test_cloud_video_creation_composites_and_reviews_all_frames(self):
        import shutil
        from pathlib import Path
        from server import video_api as video, providers
        q,_=self.bundle_plan()
        asset=studio.quotes.loads(q['quote'])['specs'][0]['asset']
        q=post(self.c,'creations/plan',asset=asset,brief='抹茶饮品上新，只要9秒短视频，48元/罐').json
        platform='custom-'+uuid.uuid4().hex
        try:
            with studio.db(True) as c:
                providers.save(c,'test',dict(id=platform,label='视频测试',capability='video',url='https://video.example/tasks',model='fixture-video',key='video-private'))
                providers.select(c,'test',dict(video=platform,text='local-rules',image='local-rules',vision='local-rules'))
            with tempfile.TemporaryDirectory() as directory:
                source=Path(directory)/'source.mp4'
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=0xadbfa3:size=360x640:rate=24','-vf',"drawbox=x=20:y=100:w=50:h=50:color=white:t=fill",'-t','1','-pix_fmt','yuv420p',str(source)],check=True)
                def respond(cfg,url,payload=None):
                    return dict(id='task-render') if payload else dict(status='succeeded',content=dict(video_url='https://cdn.example/video.mp4'))
                with patch.object(video,'request_json',side_effect=respond), patch.object(video,'download',side_effect=lambda url,dest:shutil.copy(source,dest)):
                    group=submit_with_copy(self.c,'creations',quote=q['quote'],confirmedCost=q['cost'],requestKey=uuid.uuid4().hex).json
                    for item in group['items']:
                        done=self.finish(item['job'])
                        self.assertEqual(done['state'],'complete',done)
                item=next(i for i in group['items'] if i['role']=='motion')
                result=self.c.get('/api/jobs/'+item['job']).json
                work=self.c.get('/api/works/'+result['work']).json['versions'][0]
                self.assertFalse(work.get('openDesignSource'))
                self.assertEqual(len(work['storyboard']),3)
                with self.c.get(work['download']) as download:
                    self.assertGreater(len(download.data),10000)
        finally:
            with studio.db(True) as c:
                c.execute('DELETE FROM model_route')
                c.execute('DELETE FROM model_provider WHERE id=?',(platform,))

    def test_admin_password_change_and_session_revocation(self):
        payload = dict(currentPassword=studio.ADMIN, newPassword="测试管理密码2026", confirmPassword="测试管理密码2026")
        self.assertEqual(post(self.c, "admin/password", **payload).status_code, 403)
        self.admin()
        other = studio.app.test_client()
        other.get("/api/state")
        self.assertEqual(post(other, "account/admin", password=studio.ADMIN).status_code, 200)
        try:
            self.assertEqual(post(self.c, "admin/password", **{**payload, "currentPassword": "wrong"}).status_code, 403)
            self.assertEqual(post(self.c, "admin/password", **{**payload, "confirmPassword": "different"}).status_code, 400)
            self.assertEqual(post(self.c, "admin/password", **{**payload, "newPassword": "short", "confirmPassword": "short"}).status_code, 400)
            self.assertEqual(post(self.c, "admin/password", **payload).status_code, 200)
            self.assertTrue(self.state()["admin"])
            self.assertFalse(other.get("/api/state").json["admin"])
            self.assertEqual(other.get("/api/admin").status_code, 403)
            self.assertEqual(post(other, "account/admin", password=studio.ADMIN).status_code, 403)
            self.assertEqual(post(other, "account/admin", password=payload["newPassword"]).status_code, 200)
            with studio.db() as c:
                stored = c.execute("SELECT password_hash FROM admin_auth WHERE id=1").fetchone()[0]
                self.assertNotIn(payload["newPassword"], stored)
                self.assertTrue(studio.check_password_hash(stored, payload["newPassword"]))
                logs = str([tuple(row) for row in c.execute("SELECT action,target FROM audit")])
                self.assertNotIn(payload["newPassword"], logs)
            with patch.dict(os.environ, {"TRUPIC_ADMIN_KEY": "test-deployment-managed-key"}):
                self.assertFalse(self.state()["admin"])
                self.assertEqual(post(self.c, "account/admin", password="test-deployment-managed-key").status_code, 200)
                self.assertTrue(self.c.get("/api/admin").json["adminAuth"]["environmentManaged"])
                self.assertEqual(post(self.c, "admin/password", **payload).status_code, 400)
        finally:
            with studio.db(True) as c:
                c.execute("DELETE FROM admin_auth")

    def test_merchant_selects_reviewed_poster_copy_before_any_job(self):
        brief = "给璟澜院厨房发朋友圈，周末想看样板间可以找我约个时间，做张海报。"
        q = post(self.c, "creations/plan", brief=brief).json
        self.assertTrue(q["requiresCopyChoice"])
        payload = dict(quote=q["quote"], confirmedCost=q["cost"], requestKey=uuid.uuid4().hex)
        options = [
            dict(title="你切菜，我摆盘", body="璟澜院样板间厨房。", cta="周末找我约时间。", shareTo="一起做饭的人", reply="那洗碗归谁？"),
            dict(title="晚饭做好前，先陪我聊会儿", body="璟澜院的厨房。", cta="周末约个时间来看。", shareTo="伴侣", reply="我正好想跟你说件事。"),
            dict(title="免费送厨房", body="不实的优惠", cta="", shareTo="朋友", reply="真的？"),
        ]
        def ask(prompt, inputs, tokens):
            self.assertIn("社交货币", prompt)
            self.assertIn("高端、奢侈品、地产", prompt)
            if "独立审稿人" in prompt:
                self.assertEqual(len(inputs["候选"]), 2)
                return {"approved": [0, 1]}, "test-writer"
            return {"options": options}, "test-writer"
        with patch("server.model.route", return_value=dict(model="test-writer", url="", provider="test")), patch("server.model.ask", side_effect=ask) as writer:
            choices = post(self.c, "copy-options", quote=q["quote"]).json["options"]
        self.assertEqual(writer.call_count, 2)
        self.assertEqual(len(choices), 2)
        self.assertEqual(post(self.c, "creations", **payload).status_code, 400)
        self.assertEqual(post(self.c, "creations", **payload, copyChoice="invented").status_code, 400)
        other = post(self.c, "creations/plan", brief=brief + "用横版。").json
        self.assertEqual(post(self.c, "creations", **{**payload, "quote":other["quote"]}, copyChoice=choices[1]["token"]).status_code, 400)
        self.assertFalse(self.state()["jobs"])
        self.assertEqual(self.state()["credits"], 120)
        with patch("server.auto_pipeline.generate_copy", side_effect=AssertionError("selection must be final")):
            group = post(self.c, "creations", **payload, copyChoice=choices[1]["token"]).json
            for item in group["items"]:
                self.assertEqual(self.finish(item["job"])["state"], "complete")
                version = self.c.get("/api/works/" + item["work"]).json["versions"][0]
                for field in ("title", "body", "cta"):
                    self.assertEqual(version[field], choices[1][field])
        repeat = post(self.c, "creations", **payload, copyChoice=choices[1]["token"]).json
        self.assertEqual(repeat["id"], group["id"])

    def test_auto_creation_routing_and_shared_facts(self):
        from server.auto_creation import route_request, factual_lines
        self.assertEqual(route_request('只要文案，不要视频')['roles'], ['copy'])
        self.assertEqual(route_request('只要视频')['roles'], ['copy', 'motion'])
        self.assertEqual(route_request('只要主图和卖点图')['roles'], ['copy', 'hero', 'benefit'])
        self.assertEqual(route_request('做图片和视频')['roles'], ['copy', 'poster', 'motion'])
        self.assertEqual(route_request('一张海报，不要视频')['roles'], ['copy', 'poster'])
        self.assertEqual(route_request('新品上新组图，配一个短视频')['roles'], ['copy', 'hero', 'benefit', 'scene', 'motion'])
        self.assertIn('unsupported', route_request('做一个网站'))
        self.assertEqual(factual_lines('净含量100g，9秒短视频，主标题写成「春山」', '', {}), ['净含量100g'])
        q, _ = self.bundle_plan(cutout=True)
        asset = studio.quotes.loads(q['quote'])['specs'][0]['asset']
        with patch.object(studio.model, 'chat_request', side_effect=AssertionError('No API')):
            result = post(self.c, 'creations/plan', asset=asset, brief='抹茶新品上新组图，48元/罐，净含量100g，可搭配牛奶冲调。再配一条9秒短视频。主标题写成「给牛奶加一点春山」').json
        self.assertTrue(result['ready'], result)
        self.assertEqual(result['cost'], 28)
        specs = studio.quotes.loads(result['quote'])['items']
        self.assertEqual([i['role'] for i in specs], ['copy', 'hero', 'benefit', 'scene', 'white', 'motion'])
        shared = specs[0]['spec']['plan']['coordination']
        for item in specs:
            s = item['spec']
            self.assertEqual(s['plan']['coordination'], shared)
            self.assertEqual(s['replacement']['body'], '48元/罐；净含量100g；可搭配牛奶冲调')
            self.assertEqual(s['assetMode'], 'cutout')
        missing = post(self.c, 'creations/plan', asset=asset, brief='帮我做促销海报').json
        self.assertFalse(missing['ready'])
        self.assertEqual(len(missing['questions']), 3)
        completed = post(self.c, 'creations/plan', asset=asset, brief='帮我做促销海报', facts='买一送一，本周末，全场适用，无其他限制').json
        self.assertTrue(completed['ready'], completed)
        other = studio.app.test_client()
        other.get('/api/state')
        self.assertEqual(post(other, 'creations/plan', asset=asset, brief='上新组图').status_code, 404)

    def test_auto_creation_retry_billing_and_zip(self):
        q, _ = self.bundle_plan()
        asset = studio.quotes.loads(q['quote'])['specs'][0]['asset']
        q = post(self.c, 'creations/plan', asset=asset, brief='抹茶新品上新组图，48元/罐').json
        self.assertEqual(q['cost'], 12)  # opaque input cannot gain an unreviewed white image
        payload = dict(quote=q['quote'], confirmedCost=q['cost'], requestKey=uuid.uuid4().hex)
        real = studio.render
        def fail_benefit(folder, plan, *args, **kwargs):
            if plan.get('bundleRole') == 'benefit':
                raise ValueError('测试独立重试')
            return real(folder, plan, *args, **kwargs)
        with patch.object(studio, 'render', side_effect=fail_benefit), patch.object(studio.model, 'chat_request', side_effect=AssertionError('No API')):
            pack = submit_with_copy(self.c, 'creations', **payload).json
            self.assertEqual(pack['requestKey'], payload['requestKey'])
            self.assertEqual(submit_with_copy(self.c, 'creations', **payload).json['id'], pack['id'])
            states = [self.finish(item['job'])['state'] for item in pack['items']]
        self.assertEqual(states, ['complete', 'complete', 'failed', 'complete'])
        self.assertEqual(self.state()['credits'], 112)
        self.assertEqual(self.c.get(pack['download']).status_code, 400)
        failed = pack['items'][2]['job']
        with patch.object(studio.model, 'chat_request', side_effect=AssertionError('No API')):
            post(self.c, 'jobs/' + failed + '/retry')
            self.assertEqual(self.finish(failed)['state'], 'complete')
        post(self.c, 'jobs/' + failed + '/retry')
        self.assertEqual(self.state()['credits'], 108)
        finished = self.c.get('/api/creations/' + pack['id']).json
        self.assertTrue(finished['complete'])
        self.assertIn('48元/罐', finished['items'][0]['text'])
        with zipfile.ZipFile(io.BytesIO(self.c.get(pack['download']).data)) as z:
            self.assertEqual(len(z.namelist()), 4)
        other = studio.app.test_client()
        other.get('/api/state')
        self.assertEqual(other.get(pack['download']).status_code, 404)

    def test_bundle_atomic_creation_retry_and_zip(self):
        q, payload = self.bundle_plan()
        self.assertEqual(q["roles"], ["主图", "卖点图", "场景图"])
        real_render = studio.render
        def fail_benefit(folder, plan, *args, **kwargs):
            if plan.get("bundleRole") == "benefit":
                raise ValueError("测试单张失败")
            return real_render(folder, plan, *args, **kwargs)
        with patch.object(studio, "render", side_effect=fail_benefit), patch.object(studio.model, "chat_request", side_effect=AssertionError("素材包不应调用 API")):
            pack = submit_with_copy(self.c, "bundles", **payload).json
            self.assertEqual(submit_with_copy(self.c, "bundles", **payload).json["id"], pack["id"])
            states = [self.finish(i["job"]) for i in pack["items"]]
        self.assertEqual([s["state"] for s in states], ["complete", "failed", "complete"], states)
        self.assertEqual(self.state()["credits"], 112)
        self.assertEqual(self.c.get(pack["download"]).status_code, 400)
        failed = pack["items"][1]["job"]
        post(self.c, "jobs/" + failed + "/retry")
        self.assertEqual(self.finish(failed)["state"], "complete")
        post(self.c, "jobs/" + failed + "/retry")
        self.assertEqual(self.state()["credits"], 108)
        finished = self.c.get('/api/bundles/' + pack['id']).json
        self.assertTrue(finished['complete'])
        with zipfile.ZipFile(io.BytesIO(self.c.get(pack['download']).data)) as z:
            self.assertEqual(z.namelist(), ['01-主图.png','02-卖点图.png','03-场景图.png'])
            images = [z.read(name) for name in z.namelist()]
            self.assertEqual(len(set(images)), 3)
        other = studio.app.test_client()
        self.assertEqual(other.get('/api/bundles/' + pack['id']).status_code, 404)
        self.assertEqual(other.get(pack['download']).status_code, 404)
        self.assertEqual(submit_with_copy(other, 'bundles', **{**payload, 'requestKey': uuid.uuid4().hex}).status_code, 403)

    def test_bundle_cutout_white_background(self):
        q, payload = self.bundle_plan(cutout=True)
        self.assertEqual(q['roles'][-1], '白底图')
        self.assertEqual(q['cost'], 16)
        pack = submit_with_copy(self.c, 'bundles', **payload).json
        for item in pack['items']:
            result = self.finish(item['job'])
            self.assertEqual(result['state'], 'complete', result)
        finished = self.c.get('/api/bundles/' + pack['id']).json
        white = self.c.get(finished['items'][-1]['preview']).data
        with Image.open(io.BytesIO(white)) as im:
            self.assertEqual(im.getpixel((0, 0)), (255,255,255))
        self.assertEqual(self.state()['credits'], 104)

    def test_all_creative_skill_deliveries(self):
        for skill in ("promotion", "social", "live", "brand", "mockup", "angles", "motion"):
            with self.subTest(skill=skill):
                self.setUp()
                q, _ = self.bundle_plan()
                asset = studio.quotes.loads(q["quote"])["specs"][0]["asset"]
                if skill == "brand":
                    response = post(self.c, "brand-kit", name="春山",color="#315744",logo=asset,font="")
                    self.assertEqual(response.status_code,200,response.json)
                request = dict(skill=skill,title="抹茶饮品",benefits="抹茶与牛奶搭配，28元",terms="11月25日至30日，仅限堂食",asset=asset,assetConfirmed=True,ratio="square",resolution=720,sideAsset=asset,backAsset=asset)
                q = post(self.c,"bundles/preview",**request).json
                self.assertIn("quote",q,q)
                with patch.object(studio.model,"chat_request",side_effect=AssertionError("技能不应调用 API")):
                    pack = submit_with_copy(self.c,"bundles",quote=q["quote"],confirmed=True,confirmedCost=q["cost"],requestKey=uuid.uuid4().hex).json
                    for item in pack["items"]:
                        result=self.finish(item["job"])
                        self.assertEqual(result["state"],"complete",(skill,item,result))
                finished=self.c.get('/api/bundles/'+pack['id']).json
                self.assertTrue(finished['complete'])
                response=self.c.get(pack['download'])
                with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                    self.assertGreaterEqual(len(archive.namelist()),len(pack['items']))
                response.close()
                if skill == "live":
                    response=self.c.get(finished['items'][-1]['preview'])
                    with Image.open(io.BytesIO(response.data)) as im:
                        self.assertEqual(im.mode,"RGBA")
                        self.assertEqual(im.getpixel((0,0))[3],0)
                    response.close()
                if skill == "motion":
                    source=self.c.get('/api/jobs/'+pack['items'][-1]['job']).json['work']
                    q=post(self.c,'bundles/preview',**{**request,'skill':'remake','template':source}).json
                    repack=submit_with_copy(self.c,'bundles',quote=q['quote'],confirmed=True,confirmedCost=q['cost'],requestKey=uuid.uuid4().hex).json
                    result=self.finish(repack['items'][0]['job'])
                    self.assertEqual(result['state'],'complete',result)

    def test_poster_skill_is_executed_and_library_is_admin_only(self):
        self.assertEqual(self.c.get('/api/admin').status_code, 403)
        request = dict(brief='为春山抹茶粉做一张封面海报，标题写成「给牛奶加一点春山」', kind='poster')
        with patch.object(studio.model, 'chat_request', side_effect=AssertionError('不能调用外部 API')):
            response = post(self.c, 'preview', **request)
            self.assertEqual(response.status_code, 200, response.json)
            q = response.json
            plan = q['plan']
            selected = {s['id'] for s in plan['skillPlan']['skills']}
            self.assertIn('poster_design', selected)
            self.assertIn('cover_design', selected)
            for stage in ('copy', 'image'):
                for instruction in plan['skillPlan']['instructions'][stage]:
                    self.assertIn(instruction, plan['promptBrief']['prompts'][stage])
            job = submit_with_copy(self.c, 'jobs', quote=q['quote'], confirmed=True, confirmedCost=q['cost'], requestKey=uuid.uuid4().hex).json
            result = self.finish(job['id'])
            self.assertEqual(result['state'], 'complete', result)
        with studio.db() as c:
            saved = json.loads(c.execute('SELECT spec FROM version WHERE work=?', (result['work'],)).fetchone()[0])
        self.assertEqual(saved['plan']['skillPlan'], plan['skillPlan'])
        self.admin()
        library = self.c.get('/api/admin').json['skills']
        self.assertTrue(any(s['id']=='poster_design' and s['status']=='integrated' for s in library))
        self.assertTrue(any(s['status']=='reserve' for s in library))
        self.assertNotIn('web_visual', [s['id'] for s in self.c.get('/api/creative-skills').json])

    def test_consent_and_concurrent_replay(self):
        payload = self.plan()
        self.assertEqual(
            submit_with_copy(self.c, "jobs", **{**payload, "confirmed": False}).status_code, 400
        )
        cookie = self.c.get_cookie("trupic_workspace").value

        def submit(_):
            c = studio.app.test_client()
            c.set_cookie("trupic_workspace", cookie)
            return submit_with_copy(c, "jobs", **payload).json["id"]

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
        self.assertEqual(submit_with_copy(other, "jobs", **payload).status_code, 403)

    def test_failure_retry_only_charges_on_success(self):
        with patch.object(studio, "render", side_effect=ValueError("测试制作中断")):
            j = submit_with_copy(self.c, "jobs", **self.plan()).json
            self.assertEqual(self.finish(j["id"])["state"], "failed")
        self.assertEqual(self.state()["credits"], 120)
        with patch.object(
            studio, "generate_copy", side_effect=AssertionError("重试应复用已审文案")
        ):
            post(self.c, "jobs/" + j["id"] + "/retry")
            self.assertEqual(self.finish(j["id"])["state"], "complete")
        post(self.c, "jobs/" + j["id"] + "/retry")
        self.assertEqual(self.state()["credits"], 116)

    def test_suggestion_and_versions(self):
        job = submit_with_copy(self.c, "jobs", **self.plan()).json
        self.finish(job["id"])
        url = "works/" + job["work"]
        one = self.c.get("/api/" + url).json["versions"][0]
        j = submit_revision(self.c, url + "/revise", base=1, requestKey=uuid.uuid4().hex).json
        self.assertEqual(self.finish(j["id"])["state"], "complete")
        versions = self.c.get("/api/" + url).json["versions"]
        self.assertEqual(versions[0]["title"], one["suggestion"]["title"])
        self.assertNotEqual(versions[0]["title"], versions[1]["title"])
        post(self.c, url + "/restore/1")
        self.assertEqual(self.state()["works"][0]["current"], 1)
        self.assertEqual(self.state()["credits"], 115)

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
            j = submit_with_copy(self.c, "jobs", **self.plan(kind)).json
            self.assertEqual(self.finish(j["id"])["state"], "complete")
            w = self.c.get("/api/works/" + j["work"]).json["versions"][0]
            out = self.c.get(w["download"])
            self.assertGreater(len(out.data), 30)
            if kind == "video":
                self.assertIn(
                    next(item["detail"] for item in w["quality"] if item["label"] == "短片渲染引擎"),
                    {"HyperFrames", "FFmpeg"},
                )
                source = self.c.get(w["openDesignSource"])
                self.assertEqual(source.status_code, 200)
                self.assertIn("OpenDesign.zip", source.headers["Content-Disposition"])
                with zipfile.ZipFile(io.BytesIO(source.data)) as project:
                    self.assertEqual(project.read("video.mp4"), out.data)
                    html = project.read("index.html").decode("utf-8")
                    self.assertIn('href="video.mp4"', html)
                    self.assertIn('data-fps="24"', html)
                    self.assertIn('id="soundtrack"', html)
                    self.assertIn(w["storyboard"][1]["line"], project.read("captions.srt").decode())
                    for shot in range(1, 4):
                        self.assertIn(f'id="picture-{shot}"', html)
                        self.assertIn(f'id="title-{shot}"', html)
                        self.assertIn(f"assets/title-{shot}.svg", project.namelist())
                source.close()
                other = studio.app.test_client()
                other.get("/api/state")
                self.assertEqual(other.get(w["openDesignSource"]).status_code, 404)
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

    def test_one_click_auto_grid_and_layout_revision_share_the_same_renderer(self):
        quote, _ = self.bundle_plan(cutout=True)
        asset = studio.quotes.loads(quote["quote"])["specs"][0]["asset"]
        for brief, facts, first, mode in (
            ("抹茶粉新品上新，做一张海报", "净含量100g", "product", "bleed"),
            ("抹茶粉促销，做一张海报", "第二件半价，本周末，仅限到店", "offer", "bleed"),
        ):
            with self.subTest(brief=brief):
                quote = post(self.c, "creations/plan", asset=asset, brief=brief, facts=facts).json
                group = submit_with_copy(self.c, "creations", quote=quote["quote"], confirmedCost=quote["cost"],
                             requestKey=uuid.uuid4().hex).json
                item = next(i for i in group["items"] if i["kind"] == "poster")
                self.assertEqual(self.finish(item["job"])["state"], "complete")
                url = "works/" + item["work"]
                old = self.c.get("/api/" + url).json["versions"][0]
                self.assertEqual(old["plan"]["design"]["photoLayout"], mode)
                self.assertEqual(old["plan"]["design"]["readingOrder"]["first"], first)
                job = submit_revision(self.c, url + "/revise", base=1, action="layout", requestKey=uuid.uuid4().hex).json
                self.assertEqual(self.finish(job["id"])["state"], "complete")
                new = self.c.get("/api/" + url).json["versions"][0]
                self.assertNotEqual(new["plan"]["design"]["photoLayout"], mode)
                self.assertEqual(new["plan"]["design"]["readingOrder"], old["plan"]["design"]["readingOrder"])
                for version in (old, new):
                    self.assertEqual(version["plan"]["posterArt"]["composition"], "photo-grid")
                    with self.c.get(version["designSource"]) as svg:
                        self.assertIn(b'id="source-photo"', svg.data)
                        self.assertEqual(b'id="picture-frame"' in svg.data, version["plan"]["design"]["photoLayout"] == "framed")
                for field in ("title", "body", "cta", "offer", "terms", "asset"):
                    self.assertEqual(old[field], new[field])

    def test_first_draft_uses_both_photo_and_business_intent(self):
        # Real renderable fixtures; hold the words fixed, then hold the photo fixed.
        assets = {}
        for name in ("hotpot", "beauty", "retail"):
            path = studio.ROOT / "server" / "scenes" / (name + ".webp")
            with path.open("rb") as f, patch.dict(os.environ, TRUPIC_CUTOUT="/missing"):
                assets[name] = self.c.post("/api/assets", data={"image": (f, path.name)}).json["id"]
        ordinary = "店里刚上新了，帮我做一张海报发朋友圈。"
        for name, brief, style, mode in (
            ("hotpot", ordinary, "photo-grid", "bleed"),
            ("beauty", ordinary, "quiet-light", None),
            ("retail", ordinary, "photo-grid", "bleed"),
            ("hotpot", "这款上新了，周末去市集摆摊，路过就能看见，做一张海报。", "riso", None),
            ("hotpot", "这款上新了，周末去市集摆摊，做一张海报，不要孔版。", "photo-grid", "bleed"),
            ("hotpot", "周末去市集，做一张全图海报。", "photo-grid", "bleed"),
            ("hotpot", "周末去市集，做一张海报，不要取景框。", "riso", None),
            ("beauty", "新品上架，要一张取景框海报。", "photo-grid", "framed"),
        ):
            with self.subTest(name=name, brief=brief):
                quote = post(self.c, "creations/plan", asset=assets[name], assetMode="original",
                             assetConfirmed=True, brief=brief).json
                self.assertTrue(quote["ready"], quote)
                spec = next(item["spec"] for item in studio.quotes.loads(quote["quote"])["items"]
                            if item["spec"]["kind"] == "poster")
                design = spec["plan"]["design"]
                self.assertEqual((design["id"], design.get("photoLayout")), (style, mode))
                self.assertIn(design["readingOrder"]["layoutReason"], spec["plan"]["promptBrief"]["prompts"]["image"])
                if style == "riso":
                    group = submit_with_copy(self.c, "creations", quote=quote["quote"], confirmedCost=quote["cost"],
                                 requestKey=uuid.uuid4().hex).json
                    item = next(row for row in group["items"] if row["kind"] == "poster")
                    self.assertEqual(self.finish(item["job"])["state"], "complete")
                    version = self.c.get("/api/works/" + item["work"]).json["versions"][0]
                    self.assertEqual(version["plan"]["design"], design)
                    with self.c.get(version["designSource"]) as svg:
                        self.assertIn(b'id="primary-ink"', svg.data)

    def test_reference_poster_layouts_export_editable_photos_and_copy(self):
        for style, brief, photo, ratio in (
            ("food-motion", "为牛肉火锅制作日式美食海报，居酒屋暗调。", "hotpot", "portrait"),
            ("quiet-light", "为木质香水做留白光影海报，标题写「闻见安静」。", "beauty", "square"),
            ("photo-grid", "用取景框照片编排展示试驾，标题写「照片里，握不到方向盘」。", "auto", "landscape"),
        ):
            with self.subTest(style=style):
                original = studio.ROOT / "server" / "scenes" / f"{photo}.webp"
                asset = self.c.post(
                    "/api/assets", data={"image": (io.BytesIO(original.read_bytes()), original.name)}
                ).json
                req = dict(
                    brief=brief, kind="poster", asset=asset["id"], assetMode="original",
                    assetConfirmed=True, ratio=ratio, resolution=720,
                )
                quote = post(self.c, "preview", **req).json
                self.assertEqual(quote["plan"]["design"]["id"], style)
                self.assertEqual(quote["plan"]["posterArt"]["composition"], style)
                if style == "food-motion":
                    self.assertEqual(quote["plan"]["posterArt"]["lighting"], "dark")
                job = submit_with_copy(
                    self.c, "jobs", **req, confirmed=True, confirmedCost=quote["cost"],
                    quote=quote["quote"], requestKey=uuid.uuid4().hex,
                ).json
                status = self.finish(job["id"])
                self.assertEqual(status["state"], "complete", status)
                version = self.c.get(f"/api/works/{job['work']}").json["versions"][0]
                with self.c.get(version["designSource"]) as svg:
                    self.assertEqual(svg.status_code, 200)
                    self.assertIn(b'id="source-photo"', svg.data)
                    self.assertIn(b'id="typography"', svg.data)
                    if style == "photo-grid":
                        self.assertIn(b'id="picture-frame"', svg.data)
                if style == "photo-grid":
                    url = "works/" + job["work"]
                    for base, mode in ((1, "bleed"), (2, "framed")):
                        j = submit_revision(self.c, url + "/revise", base=base, action="layout", requestKey=uuid.uuid4().hex).json
                        done = self.finish(j["id"])
                        self.assertEqual(done["state"], "complete", done)
                        versions = self.c.get("/api/" + url).json["versions"]
                        latest = versions[0]
                        self.assertEqual(len(versions), base + 1)
                        self.assertEqual(latest["plan"]["design"]["id"], style)
                        self.assertEqual(latest["plan"]["design"]["photoLayout"], mode)
                        for field in ("title", "offer", "terms", "body", "cta", "asset", "ratio"):
                            self.assertEqual(latest[field], version[field])
                        with self.c.get(latest["designSource"]) as svg:
                            self.assertIn(b'id="source-photo"', svg.data)
                            self.assertEqual(b'id="picture-frame"' in svg.data, mode == "framed")

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

    def test_topic_adoption_only_after_delivery(self):
        post(self.c, "profile", name="春野", product="菌菇火锅", industry="火锅")
        topic = self.c.get("/api/topics").json[0]
        req = {"brief": topic["brief"], "topicId": topic["topicId"], "kind": "copy"}
        other = studio.app.test_client()
        self.assertEqual(post(other, "preview", **req).status_code, 400)
        preview = post(self.c, "preview", **req).json
        self.assertEqual(preview["plan"]["topic"]["title"], topic["title"])

        def adopted():
            return next(
                i["adopted"]
                for i in self.state()["recs"]
                if i["topicId"] == topic["topicId"]
            )

        self.assertFalse(adopted())
        with patch.object(studio, "render", side_effect=ValueError("测试制作中断")):
            job = submit_with_copy(
                self.c, "jobs", quote=preview["quote"], requestKey=uuid.uuid4().hex
            ).json
            self.assertEqual(self.finish(job["id"])["state"], "failed")
        self.assertFalse(adopted())
        post(self.c, "jobs/" + job["id"] + "/retry")
        self.assertEqual(self.finish(job["id"])["state"], "complete")
        self.assertTrue(adopted())
        self.assertEqual(self.state()["credits"], 120)

    def test_visual_preflight_detailed_area_and_semantic_source(self):
        from PIL import ImageDraw

        pic = Image.new("RGB", (540, 400), "white")
        draw = ImageDraw.Draw(pic)
        for x in range(0, 240, 6):
            draw.rectangle((x, 0, x + 2, 399), fill="navy")
        stream = io.BytesIO()
        pic.save(stream, "PNG")
        stream.seek(0)
        asset = self.c.post("/api/assets", data={"image": (stream, "package.png")}).json
        self.assertFalse(asset["risk"])
        req = {
            "asset": asset["id"],
            "assetConfirmed": True,
            "assetMode": "original",
            "brief": "保留包装文字，给商品做海报",
            "kind": "poster",
        }
        self.assertEqual(post(self.c, "preview", **req).status_code, 400)
        self.assertEqual(
            post(
                self.c, "preview", **req, identityRegion=[0.60, 0.24, 0.85, 0.55]
            ).status_code,
            400,
        )
        req["identityRegion"] = [0.05, 0.1, 0.35, 0.5]
        self.assertEqual(post(self.c, "preview", **req).status_code, 200)
        with (
            patch.dict(os.environ, TRUPIC_VISION_MODEL="视觉测试"),
            patch(
                "server.model.chat_request",
                return_value={"ok": False, "reason": "包装被手遮挡"},
            ) as remote,
        ):
            denied = post(self.c, "preview", **req)
            self.assertIn("包装被手遮挡", denied.json["error"])
            self.assertEqual(
                sum(
                    v["type"] == "image_url"
                    for v in remote.call_args.args[2][1]["content"]
                ),
                2,
            )
        self.assertEqual(self.state()["credits"], 120)

    def test_video_preflight_pairs_observed_detail_with_a_supported_short_claim(self):
        q, _ = self.bundle_plan()
        asset = studio.quotes.loads(q["quote"])["specs"][0]["asset"]
        req = dict(kind="video", brief="给抹茶饮品制作商品短片。", facts="杯壁能看到茶奶分层",
                   asset=asset, assetConfirmed=True, assetMode="original")
        detail = dict(region=[0.52, 0.35, 0.78, 0.58], label="茶奶分层", claim=req["facts"])
        for observation, accepted, line in (
            (detail, True, req["facts"]),
            ({**detail, "claim": "口感更香浓"}, True, detail["label"]),
            ({**detail, "region": [0.2, 0.1, 0.20001, 0.7]}, False, "商品实拍"),
            ({**detail, "region": [0, 0, 800, 600]}, False, "商品实拍"),
        ):
            with patch.dict(os.environ, TRUPIC_VISION_MODEL="视觉测试"), patch(
                "server.model.chat_request", return_value=dict(ok=True, reason="饮品可见", visualDetail=observation)
            ):
                plan = post(self.c, "preview", **req).json["plan"]
            self.assertEqual(bool(plan["sourceReview"].get("visualDetail")), accepted)
            shot = studio.storyboard(plan, dict(title="先别搅", body=req["facts"], cta=""))[1]
            self.assertEqual(shot["line"], line)
        for invalid in ({"label": "拨盘", "region": [0, 0, -1, 1]}, {"label": "续航24小时", "region": detail["region"]}):
            self.assertEqual(post(self.c, "preview", **req, visualDetail=invalid).status_code, 400)

    def test_poster_repairs_overwritten_product_and_blocks_failed_recheck(self):
        from pathlib import Path
        from PIL import ImageDraw

        with open(Path(studio.ROOT) / "miniprogram/images/tea.jpg", "rb") as f:
            asset = self.c.post(
                "/api/assets", data={"image": (io.BytesIO(f.read()), "tea.jpg")}
            ).json
        req = {
            "kind": "poster",
            "asset": asset["id"],
            "assetConfirmed": True,
            "assetMode": "original",
            "brief": "为茶饮做一张商品海报",
            "resolution": 720,
        }
        render = studio.render

        def overwrite(*args, **kwargs):
            layout = render(*args, **kwargs)
            if not kwargs.get("repair") or always:
                dest = args[0] / "poster.png"
                with Image.open(dest) as saved:
                    im = saved.copy()
                box = layout["frames"][0]["product"]
                ImageDraw.Draw(im).rectangle(box, fill="red")
                im.save(dest, dpi=(300, 300))
            return layout

        self.admin()
        req["quote"] = post(self.c, "preview", **req).json["quote"]
        for always in (False, True):
            with patch.object(studio, "render", side_effect=overwrite):
                job = submit_with_copy(
                    self.c,
                    "jobs",
                    **req,
                    confirmed=True,
                    confirmedCost=4,
                    requestKey=uuid.uuid4().hex,
                ).json
                result = self.finish(job["id"])
            report = next(
                v["report"]
                for v in self.c.get("/api/admin").json["visualReviews"]
                if v["id"] == job["id"]
            )
            self.assertEqual(len(report["attempts"]), 2)
            self.assertTrue(
                any("商品局部" in i for i in report["attempts"][0]["issues"])
            )
            self.assertEqual(
                report["status"], "blocked" if always else "repaired", report
            )
            self.assertEqual(
                result["state"], "failed" if always else "complete", result
            )
            self.assertEqual(self.state()["credits"], 116)
        self.assertEqual(len(self.state()["works"]), 1)

    def test_print_source_separates_inks_subject_and_editable_copy(self):
        import xml.etree.ElementTree as ET
        from pathlib import Path

        with (Path(studio.ROOT) / "miniprogram/images/tea.jpg").open("rb") as fp:
            asset = self.c.post("/api/assets", data={"image": (fp, "tea.jpg")}).json
        for direction, second_ink in (("蓝墨单色印刷", False), ("蓝墨橙墨双色印刷", True)):
            quote = post(self.c, "preview", kind="poster", brief=direction + "海报，标题「茶与光」。不要行动号召。",
                         asset=asset["id"], assetConfirmed=True, resolution=720, lettering="both").json
            self.assertEqual(quote["plan"]["design"]["id"], "riso")
            job = submit_with_copy(self.c, "jobs", quote=quote["quote"], confirmed=True,
                       confirmedCost=quote["cost"], requestKey=uuid.uuid4().hex).json
            result = self.finish(job["id"])
            self.assertEqual(result["state"], "complete", result)
            version = self.c.get("/api/works/" + job["work"]).json["versions"][0]
            response = self.c.get(version["designSource"])
            self.assertEqual(response.status_code, 200)
            root = ET.fromstring(response.data)
            ids = {el.get("id") for el in root}
            self.assertTrue({"paper", "primary-ink", "subject", "typography", "letterforms"} <= ids)
            self.assertEqual("accent-ink" in ids, second_ink)
            self.assertIn("茶与光", "".join(root.itertext()))
            stranger = studio.app.test_client()
            stranger.get("/api/state")
            self.assertEqual(stranger.get(version["designSource"]).status_code, 404)

    def test_food_title_and_reference_subject_remain_independent(self):
        import xml.etree.ElementTree as ET
        from server.posters import SCENES

        with Image.open(SCENES / "matcha-campaign.webp") as photo, Image.open(SCENES / "masks/matcha-campaign.png") as matte:
            sample = photo.convert("RGBA")
            sample.putalpha(matte.convert("L").resize(sample.size))
            sample = sample.crop(sample.getchannel("A").getbbox())
            sample.thumbnail((600, 600))
        stream = io.BytesIO()
        sample.save(stream, "PNG")
        stream.seek(0)
        asset = self.c.post("/api/assets", data={"image": (stream, "tea.png")}).json
        quote = post(self.c, "preview", kind="poster", posterStyle="product",
                     brief="冰抹茶拿铁，食材大字与实物穿插。标题「把春天搅开」。不要行动号召。",
                     asset=asset["id"], assetMode="processed", assetConfirmed=True, resolution=720).json
        self.assertEqual(quote["plan"]["posterArt"]["composition"], "ingredient")
        job = submit_with_copy(self.c, "jobs", quote=quote["quote"], confirmed=True,
                   confirmedCost=quote["cost"], requestKey=uuid.uuid4().hex).json
        self.assertEqual(self.finish(job["id"])["state"], "complete")
        version = self.c.get("/api/works/" + job["work"]).json["versions"][0]
        svg = ET.fromstring(self.c.get(version["designSource"]).data)
        groups = {g.get("id"):g for g in svg}
        self.assertLess(list(groups).index("model-lettering"), list(groups).index("subject"))
        self.assertEqual("".join(groups["model-lettering"].itertext()), "抹茶")
        self.assertIn("把春天搅开", "".join(groups["typography"].itertext()))

        for mode, expected in (("processed", "material"), ("original", "photograph")):
            q = post(self.c, "preview", kind="poster", posterStyle="product",
                     brief="冰抹茶拿铁，标题「把春天搅开」。不要食材大字。仅限堂食。",
                     asset=asset["id"], assetConfirmed=True, assetMode=mode, resolution=720).json
            art = q["plan"]["posterArt"]
            self.assertEqual(art["composition"], expected)
            self.assertFalse(art["modelMark"])
            task = submit_with_copy(self.c, "jobs", quote=q["quote"], confirmed=True,
                        confirmedCost=q["cost"], requestKey=uuid.uuid4().hex).json
            self.assertEqual(self.finish(task["id"])["state"], "complete")
            result = self.c.get("/api/works/" + task["work"]).json["versions"][0]
            prompt = result["fullPosterPrompt"]
            for literal in ("把春天搅开", "仅限堂食", "720"):
                self.assertIn(literal, prompt)
            self.assertNotIn("只设计空背景", prompt)

    def test_whole_frame_composition_can_reject_a_visible_product(self):
        from pathlib import Path
        from server.visual_review import compact_review

        spec = {"kind": "poster", "plan": {"profile": {"product": "茶杯"}, "subject": "茶杯"}}
        with tempfile.TemporaryDirectory() as dest:
            Image.new("RGB", (180, 240), "green").save(Path(dest) / "poster.png")
            with patch("server.model.chat_request", side_effect=[
                {"status": "pass", "reason": "杯身可辨"},
                {"status": "repair", "reason": "标题盖住杯口标志"},
            ]):
                review = compact_review(Path(dest), spec, {"provider": "local", "model": "test"},
                                        {"frames": [{"product": [20, 25, 140, 205]}]})
            self.assertEqual(review["status"], "repair")
            self.assertIn("标题盖住", review["reason"])

    def test_existing_character_poster_requires_reference(self):
        response = post(self.c, "preview", kind="poster", brief="吉祥物在橘园伸手摘橘子")
        self.assertEqual(response.status_code, 400)
        self.assertIn("角色参考图", response.json["error"])

    def test_audio_video_review_uses_actual_middle_shot(self):
        render = studio.render

        def damage(*args, **kwargs):
            layout = render(*args, **kwargs)
            if not kwargs.get("repair"):
                video = args[0] / "video.mp4"
                damaged = video.with_name("damaged.mp4")
                subprocess.run(
                    [
                        "ffmpeg",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(video),
                        "-vf",
                        "drawbox=color=black:t=fill:enable='between(t,3,5.99)'",
                        "-c:a",
                        "copy",
                        str(damaged),
                    ],
                    check=True,
                )
                damaged.replace(video)
            return layout

        self.admin()
        with patch.object(studio, "render", side_effect=damage):
            job = submit_with_copy(self.c, "jobs", **self.plan("video")).json
            result = self.finish(job["id"])
        self.assertEqual(result["state"], "complete", result)
        import zipfile
        version = self.c.get("/api/works/" + job["work"]).json["versions"][0]
        response = self.c.get(version["editSource"])
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as bundle:
            self.assertIsNone(bundle.testzip())
            timeline = json.loads(bundle.read("timeline.json"))
            self.assertEqual([shot["startFrame"] for shot in timeline["shots"]], [0, 72, 144])
            self.assertEqual(timeline["shots"][-1]["endFrameExclusive"], 216)
            for entry in timeline["shots"]:
                self.assertIn(entry["titleLayer"], bundle.namelist())
            self.assertIn("00:00:06,000 --> 00:00:09,000", bundle.read("captions.srt").decode())
            self.assertGreater(bundle.getinfo("picture.mp4").file_size, 1000)
            self.assertGreater(bundle.getinfo("soundtrack.wav").file_size, 1000)
        report = next(
            x["report"]
            for x in self.c.get("/api/admin").json["visualReviews"]
            if x["id"] == job["id"]
        )
        self.assertEqual(report["status"], "repaired")
        self.assertTrue(
            any(
                "镜头 2" in i and "分镜不符" in i
                for i in report["attempts"][0]["issues"]
            )
        )
        self.assertEqual(report["attempts"][1]["issues"], [])
        self.assertEqual(self.state()["credits"], 108)

    def test_semantic_review_checks_frames_and_rechecks_repairs(self):
        self.admin()
        req = self.plan("video")
        replies = [
            {"status": "repair", "reason": "字幕压住商品。"},
            {"status": "pass", "reason": "分镜文字与商品分区清楚。"},
        ]
        with (
            patch.dict(os.environ, TRUPIC_VISION_MODEL="视觉测试"),
            patch("server.model.chat_request", side_effect=replies) as remote,
        ):
            job = submit_with_copy(self.c, "jobs", **req).json
            result = self.finish(job["id"])
        self.assertEqual(result["state"], "complete", result)
        self.assertEqual(remote.call_count, 2)
        for call in remote.call_args_list:
            content = call.args[2][1]["content"]
            self.assertEqual(sum(x["type"] == "image_url" for x in content), 4)
        with (
            patch.dict(os.environ, TRUPIC_VISION_MODEL="视觉测试"),
            patch("server.model.chat_request", side_effect=OSError("offline")),
        ):
            j = submit_with_copy(self.c, "jobs", **{**req, "requestKey": uuid.uuid4().hex}).json
            self.assertEqual(self.finish(j["id"])["state"], "failed")
        self.assertEqual(self.state()["credits"], 108)

    def test_weekly_preference_and_observed_response_rates(self):
        from server.creative import recommendations

        profile = {"product": "菌菇火锅"}
        items = recommendations(profile, [])
        favorite = items[-1]["tag"]
        ranked = recommendations(profile, [{"preferredTag": favorite}])
        self.assertEqual(ranked[0]["tag"], favorite)
        self.admin()
        job = submit_with_copy(self.c, "jobs", **self.plan("copy")).json
        self.finish(job["id"])
        resp = post(
            self.c,
            "admin/review",
            id=job["work"],
            n=1,
            rating="合格",
            views=100,
            clicks=7,
            metrics="自有渠道，测试日",
        )
        self.assertEqual(resp.status_code, 200)
        metrics = self.c.get("/api/admin").json["effects"]
        self.assertTrue(any(x["ctr"] == 7 and x["ctrSamples"] >= 1 for x in metrics))

    def test_contrast_is_measured_in_delivered_pixels(self):
        from PIL import ImageDraw
        from server.visual_review import text_check
        from server.typography import Typesetter

        ts = Typesetter()
        ts.audit_text = []
        image = Image.new("RGB", (300, 180), "#aaaaaa")
        ts.draw(
            ImageDraw.Draw(image), "包装文字", (10, 10, 250, 100), 40, "body", "#999999"
        )
        self.assertIn(
            "对比", text_check(image, ts.audit_text, (0, 0, 300, 180), image.size)
        )

    def test_opt_in_method_retrieval_matches_and_can_be_disabled(self):
        self.admin()
        post(
            self.c,
            "admin/case",
            title="近景问题",
            source="https://example.org/" + uuid.uuid4().hex,
            license="测试",
            kind="视频",
            category="创意方法",
            tags="午休",
            scenario="新客",
            lesson="用可见的动作引出问题。",
        )
        case = self.c.get("/api/admin").json["cases"][0]
        post(self.c, "admin/approve", id=case["id"])
        post(
            self.c,
            "admin/rule",
            name="跨媒介方法",
            method="question",
            reason="测试",
            case_id=case["id"],
        )
        rule = self.c.get("/api/admin").json["rules"][0]
        req = {"kind": "poster", "brief": "为午休时的台球室做海报"}
        self.assertNotIn("retrievedMethod", post(self.c, "preview", **req).json["plan"])
        self.assertEqual(
            post(self.c, "admin/retrieval", id=rule["id"], enabled=True).status_code,
            200,
        )
        plan = post(self.c, "preview", **req).json["plan"]
        self.assertEqual(plan["retrievedMethod"]["id"], case["id"])
        self.assertIn("用可见的动作", plan["promptBrief"]["prompts"]["image"])
        post(self.c, "admin/retrieval", id=rule["id"], enabled=False)
        self.assertNotIn("retrievedMethod", post(self.c, "preview", **req).json["plan"])

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
            tags="新客,开场",
            scenario="新品上市",
        )
        self.assertEqual(r.status_code, 200)
        case = next(
            c["id"]
            for c in self.c.get("/api/admin").json["cases"]
            if c["title"] == "测试案例"
        )
        post(self.c, "admin/approve", id=case)
        stored = next(
            c for c in self.c.get("/api/admin").json["cases"] if c["id"] == case
        )
        self.assertEqual(
            (stored["tags"], stored["scenario"]), ("新客,开场", "新品上市")
        )
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

    def test_custom_platforms_can_coexist_and_keep_routes(self):
        from server import model

        self.admin()
        first, second = ("custom-" + uuid.uuid4().hex for _ in range(2))
        for platform, title in ((first, "文本服务 A"), (second, "图像审核 B")):
            result = post(self.c, "admin/model-platform", id=platform, label=title,
                          url="http://localhost:7395/v1/chat/completions",
                          text="text-" + platform, vision="vision-" + platform)
            self.assertEqual(result.status_code, 200, result.json)
        try:
            result = post(self.c, "admin/model-routes", text=first, vision=second)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(model.route("text")["provider"], first)
            self.assertEqual(model.route("vision")["provider"], second)
            config = self.c.get("/api/admin").json["modelPlatforms"]
            labels = {row["id"]: row["label"] for row in config["platforms"]}
            self.assertEqual((labels[first], labels[second]), ("文本服务 A", "图像审核 B"))
            invalid = post(self.c, "admin/model-routes", text=second, vision="unknown")
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(model.route("text")["provider"], first)
        finally:
            post(self.c, "admin/model-routes", text="", vision="")

    def test_platform_routes_keys_and_usage(self):
        from server import model
        from server.store import db, now

        self.assertEqual(
            post(self.c, "admin/model-platform", id="local").status_code, 403
        )
        self.admin()
        cfg = self.c.get("/api/admin").json["modelPlatforms"]
        self.assertTrue(
            {"atlas", "ark", "bailian", "deepseek"}
            <= {r["id"] for r in cfg["platforms"]}
        )
        try:
            for platform, kind, key in [
                ("deepseek", "text", "test-text-key"),
                ("ark", "vision", "test-vision-key"),
            ]:
                preset = next(p for p in cfg["platforms"] if p["id"] == platform)
                saved = post(
                    self.c,
                    "admin/model-platform",
                    **{**preset, kind: "sample-" + kind, "key": key},
                )
                self.assertEqual(saved.status_code, 200, saved.json)
            routes = {"text": "deepseek", "vision": "ark"}
            self.assertEqual(
                post(self.c, "admin/model-routes", **routes).status_code, 200
            )
            self.assertEqual(
                post(self.c, "admin/model-routes", text="", vision="local").status_code,
                400,
            )
            self.assertEqual(
                self.c.get("/api/admin").json["modelPlatforms"]["routes"], routes
            )
            self.assertNotIn(
                "test-vision-key", self.c.get("/api/admin").get_data(as_text=True)
            )
            self.assertEqual(model.engine_name(), "sample-text")
            self.assertEqual(model.route("vision")["key"], "test-vision-key")

            def respond(request, timeout):
                payload = json.loads(request.data)
                is_vision = payload["model"] == "sample-vision"
                self.assertEqual(
                    request.get_header("Authorization"),
                    "Bearer test-" + ("vision" if is_vision else "text") + "-key",
                )
                self.assertEqual(
                    request.full_url,
                    next(
                        p["url"]
                        for p in cfg["platforms"]
                        if p["id"] == ("ark" if is_vision else "deepseek")
                    ),
                )
                if is_vision:
                    import base64

                    image = payload["messages"][0]["content"][1]["image_url"]["url"]
                    with Image.open(
                        io.BytesIO(base64.b64decode(image.split(",")[1]))
                    ) as card:
                        r, g, b = card.convert("RGB").getpixel((50, 50))
                    color = (
                        "yellow"
                        if min(r, g) > 200
                        else "red"
                        if r > 200
                        else "blue"
                        if b > 200
                        else "green"
                    )
                    reply = {"color": color}
                else:
                    reply = {"ok": True}
                return io.BytesIO(
                    json.dumps(
                        {
                            "choices": [{"message": {"content": json.dumps(reply)}}],
                            "usage": {"prompt_tokens": 30, "completion_tokens": 6},
                        }
                    ).encode()
                )

            with patch("urllib.request.urlopen", side_effect=respond):
                self.assertEqual(post(self.c, "admin/test-model").status_code, 200)
                self.assertEqual(post(self.c, "admin/test-vision").status_code, 200)
            with patch("urllib.request.urlopen", side_effect=OSError("unavailable")):
                self.assertEqual(post(self.c, "admin/test-vision").status_code, 400)
            usage = self.c.get("/api/admin").json["modelUsage"]
            vision = next(r for r in usage if r["model"] == "sample-vision")
            self.assertEqual(
                (
                    vision["calls"],
                    vision["succeeded"],
                    vision["inputTokens"],
                    vision["inputReports"],
                ),
                (2, 1, 30, 1),
            )
            self.assertEqual(
                post(
                    self.c,
                    "admin/model-platform",
                    id="ark",
                    url="https://other.example/v1/chat/completions",
                    vision="sample-vision",
                ).status_code,
                400,
            )
            self.assertEqual(model.route("vision")["key"], "test-vision-key")
            self.assertEqual(
                post(
                    self.c,
                    "admin/model-platform",
                    id="ark",
                    url=model.route("vision")["url"],
                    text="only-text",
                ).status_code,
                400,
            )
        finally:
            with db(True) as c:
                c.execute("DELETE FROM model_route")
                c.execute("DELETE FROM model_provider WHERE id IN ('ark','deepseek')")
                c.execute(
                    "DELETE FROM model_call WHERE day=? AND model IN ('sample-vision','sample-text')",
                    (now()[:10],),
                )

    def test_qwen_image_full_poster_and_reference_free_scene(self):
        import base64
        from pathlib import Path
        from server.qwen_image import generate

        cfg = dict(imageUrl="https://example.invalid/images/generations",
                   imageKey="fixture", imageModel="qwen-image-3.0-pro")
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "product.png"
            Image.new("RGB", (512, 512), "green").save(reference)
            png = reference.read_bytes()
            encoded = base64.b64encode(png).decode()
            response = json.dumps({"data": [{"b64_json": encoded}]}).encode()
            for asset in (None, reference):
                with patch("urllib.request.urlopen", return_value=io.BytesIO(response)) as remote:
                    self.assertEqual(generate(cfg, "标题「把春天搅开」", "512x512", asset), png)
                    payload = json.loads(remote.call_args.args[0].data)
                    self.assertEqual(payload["model"], cfg["imageModel"])
                    self.assertEqual(payload["response_format"], "b64_json")
                    self.assertEqual(payload.get("image"), "data:image/png;base64," + encoded if asset else None)
            with patch("urllib.request.urlopen") as remote:
                with self.assertRaises(ValueError):
                    generate({**cfg, "imageKey": ""}, "生成海报", "512x512", reference)
                remote.assert_not_called()

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
            with (
                patch.dict(os.environ, TRUPIC_DAILY_TEXT_CALLS="0"),
                patch("urllib.request.urlopen") as remote,
            ):
                plan = prepare(
                    "为台球室写一条周末邀请",
                    {},
                    [],
                    {"name": "测试", "id": "base", "method": "moment"},
                )
                result = generate_copy(plan)
                self.assertEqual(result["engine"], "本地创意规则")
                self.assertTrue(result["reviewFlag"])
                remote.assert_not_called()
            model_response = io.BytesIO(
                json.dumps(
                    {"choices": [{"message": {"content": '{"ok":true}'}}]}
                ).encode()
            )
            with patch("urllib.request.urlopen", return_value=model_response):
                self.assertEqual(
                    post(self.c, "admin/test-model").json["model"], "fixture"
                )
                self.assertGreaterEqual(
                    self.c.get("/api/admin").json["settings"]["callsToday"]["text"], 1
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
                    "server.model.settings",
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
        self.assertEqual(quote["plan"]["design"]["id"], "photo-grid")
        self.assertEqual(quote["plan"]["design"]["readingOrder"]["first"], "offer")
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
        job = submit_with_copy(
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
            job = submit_with_copy(
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
            job = submit_with_copy(
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
