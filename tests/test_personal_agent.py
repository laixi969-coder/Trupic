"""V4 acceptance through the same Flask endpoints used by both clients."""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase
from unittest.mock import patch

from test_workflows import post, studio


class PersonalAgentTests(TestCase):
    def setUp(self):
        self.c = studio.app.test_client()
        self.state = self.c.get("/api/state").json
        self.tenant = self.state["workspace"]
        self.cid = self.conversation()

    def conversation(self, project=None, client=None):
        return post(client or self.c, "agent/conversations", project=project).json["id"]

    def send(self, text, cid=None, **params):
        reply = post(
            self.c,
            "agent/conversations/" + (cid or self.cid) + "/messages",
            **{"requestKey": uuid.uuid4().hex, "text": text, **params},
        )
        self.assertEqual(reply.status_code, 200, reply.json)
        return reply.json

    def card(self, text="为茶店做一张海报，文案用「下班来喝茶」", cid=None, **params):
        return self.send(text, cid, **params)["tasks"][-1]

    def detail(self, cid=None):
        return self.c.get("/api/agent/conversations/" + (cid or self.cid)).json

    def approval(self, t):
        return dict(
            quoteId=t["quoteId"],
            confirmedCost=t["cost"],
            revision=t["revision"],
            approvalType="production",
            requestKey="accept-" + t["id"],
        )

    def approve(self, t, client=None, **changes):
        return post(
            client or self.c,
            "agent/tasks/" + t["id"] + "/approve",
            **{**self.approval(t), **changes},
        )

    def jobs(self, t):
        with studio.db() as c:
            return [
                r["id"]
                for r in c.execute(
                    "SELECT id FROM job WHERE json_extract(spec,'$.plan.agentTask')=?",
                    (t["id"],),
                )
            ]

    def produce(self, t):
        for jid in self.jobs(t):
            studio.produce(jid)
        return next(task for task in self.detail()["tasks"] if task["id"] == t["id"])

    def shared_client(self):
        client = studio.app.test_client()
        with client.session_transaction() as s:
            s["tenant"] = self.tenant
        return client

    def test_home_resumes_active_owned_task_and_excludes_archived_or_cancelled(self):
        hello = self.send("你好。")
        self.assertFalse(hello["tasks"])
        self.assertIn("想为店里推广什么", hello["messages"][-1]["text"])
        self.assertIsNone(self.c.get("/api/agent").json["pending"])
        card = self.card()
        spoken = self.send("确认制作。", task=card["id"], revision=card["revision"])
        self.assertIn("请在任务卡上点", spoken["messages"][-1]["text"])
        self.assertEqual(spoken["tasks"][0]["quoteId"], card["quoteId"])
        self.assertEqual(self.jobs(card), [])
        another = self.conversation()
        latest = self.card(cid=another)
        home = self.c.get("/api/agent").json
        self.assertEqual(home["workspace"], self.tenant)
        self.assertEqual(home["pending"]["task"], latest["id"])
        self.assertEqual(home["pending"]["cost"], latest["cost"])
        self.assertIsNone(studio.app.test_client().get("/api/agent").json["pending"])
        self.c.delete("/api/agent/conversations/" + another, json={})
        pending = self.c.get("/api/agent").json["pending"]
        self.assertEqual((pending["conversation"], pending["task"]), (self.cid, card["id"]))
        res = post(self.c, "agent/tasks/" + card["id"] + "/cancel", revision=card["revision"])
        self.assertEqual(res.status_code, 200, res.json)
        self.assertIsNone(self.c.get("/api/agent").json["pending"])
        queued = self.card(cid=self.conversation())
        with patch.object(studio.pool, "submit"):
            self.assertEqual(self.approve(queued).status_code, 200)
        queued_home = self.c.get("/api/agent").json["pending"]
        self.assertEqual((queued_home["task"], queued_home["status"]), (queued["id"], "queued"))

    def test_scoped_memory_correction_disable_delete_and_explicit_conflict(self):
        project = post(self.c, "agent/projects", title="春季品鉴会").json["id"]
        post(self.c, "agent/memory", name="招牌", value="桂花茶")
        entry = post(
            self.c, "agent/memory", name="活动票价", value="48元", project=project
        ).json
        cid = self.conversation(project)
        t = self.card(cid=cid)
        self.assertIn("活动票价：48元", t["facts"])
        other = self.card()
        self.assertIn("招牌：桂花茶", other["facts"])
        self.assertNotIn("活动票价：48元", other["facts"])
        self.assertNotEqual(other["id"], t["id"])
        self.assertEqual(
            post(
                self.c, "agent/memory", name="活动票价", value="68元", project=project
            ).status_code,
            409,
        )
        url = "/api/agent/memory/" + entry["id"]
        self.assertEqual(
            self.c.patch(url, json=dict(version=1, value="68元")).status_code, 200
        )
        self.assertEqual(
            self.c.patch(url, json=dict(version=1, value="80元")).status_code, 409
        )
        shared = self.card(cid=self.conversation(project))
        self.assertIn("活动票价：68元", shared["facts"])
        self.c.patch(url, json=dict(version=2, active=False))
        self.assertNotIn(
            "活动票价：68元", self.card(cid=self.conversation(project))["facts"]
        )
        self.c.delete(url, json=dict(version=3))
        self.assertEqual(self.c.get(url).status_code, 404)
        self.assertEqual(
            self.c.get("/api/agent/memory?project=" + project).json["entries"][0][
                "name"
            ],
            "招牌",
        )

    def test_semantic_switch_replay_and_parallel_tasks_in_one_chat(self):
        a = self.card()
        prompt = "制作一条招聘视频"
        switch = self.send(prompt)
        self.assertEqual(switch["messages"][-1]["kind"], "switch")
        options = dict(action="branch", requestKey="branch-once")
        b = self.send(prompt, **options)
        self.assertNotEqual(b["id"], a["id"])
        self.assertEqual(b["tasks"][0]["kind"], "video")
        self.assertEqual(self.send(prompt, **options)["id"], b["id"])
        self.assertEqual(self.detail()["tasks"][0]["quoteId"], a["quoteId"])
        same = self.send(prompt, action="here")
        self.assertEqual(len(same["tasks"]), 2)
        self.assertEqual(same["tasks"][0]["status"], "quoted")

    def test_long_context_and_reload_keep_lock_and_reject_stale_approval(self):
        t = self.card()
        for _ in range(22):
            self.send("你好")
        r = self.send("复述我选的文案和规格")
        self.assertIn("下班来喝茶", r["messages"][-1]["text"])
        self.assertIn("3:4", r["messages"][-1]["text"])
        t2 = self.card(
            "构图改为横版 16:9", action="revise", task=t["id"], revision=t["revision"]
        )
        self.assertEqual(t2["locked"], t["locked"])
        self.assertEqual(t2["ratio"], "landscape")
        self.assertEqual(self.approve(t).status_code, 409)
        self.assertEqual(self.jobs(t), [])
        with patch.dict(os.environ, {"TRUPIC_PERSONAL_AGENT": "0"}):
            self.assertFalse(self.c.get("/api/state").json["personalAgent"])
            self.assertEqual(self.approve(t2).status_code, 403)
            legacy = post(
                self.c,
                "creations/plan",
                brief="为茶店做一张海报",
                deliveryMode="image",
                ratio="portrait",
            )
            self.assertTrue(legacy.json["ready"])
        self.assertEqual(
            self.shared_client()
            .get("/api/agent/conversations/" + self.cid)
            .json["tasks"][0]["quoteId"],
            t2["quoteId"],
        )

    def test_candidates_and_delegation_still_require_approval(self):
        t = self.card("给茶店做一张春季海报，都由你决定")
        self.assertEqual(t["status"], "waiting_copy")

        def options(spec, tenant):
            return [
                {
                    **spec["replacement"],
                    "title": title,
                    "body": "路过来喝一杯。",
                    "cta": "",
                }
                for title in ("下班来喝茶", "茶香在街角")
            ]

        with patch("server.copy_choices.write_options", side_effect=options):
            r = post(
                self.c, "agent/tasks/" + t["id"] + "/options", revision=t["revision"]
            )
        self.assertEqual(r.json["status"], "quoted")
        self.assertEqual(r.json["locked"]["title"], "下班来喝茶")
        self.assertFalse(self.jobs(t))
        t = self.card("为烘焙店制作一张海报", action="new")
        with patch("server.copy_choices.write_options", side_effect=options):
            post(self.c, "agent/tasks/" + t["id"] + "/options", revision=t["revision"])
        chosen = self.card("用第二组")
        self.assertEqual(chosen["locked"]["title"], "茶香在街角")
        self.assertFalse(self.jobs(chosen))

    def test_two_windows_cannot_overspend_or_double_reserve(self):
        from server import wallet

        a = self.card()
        b = self.card(cid=self.conversation())
        with studio.db(True) as c:
            c.execute(
                "UPDATE credit_lot SET remaining=0 WHERE tenant=?", (self.tenant,)
            )
            c.execute("UPDATE merchant SET credits=0 WHERE id=?", (self.tenant,))
            wallet.grant(c, self.tenant, "测试", uuid.uuid4().hex, a["cost"], None)
        with (
            patch.object(studio.pool, "submit"),
            ThreadPoolExecutor(max_workers=3) as pool,
        ):
            futures = [
                pool.submit(self.approve, t, self.shared_client()) for t in (a, a, b)
            ]
            responses = [f.result() for f in futures]
        self.assertTrue(any(r.status_code == 200 for r in responses))
        self.assertTrue(any(r.status_code == 400 for r in responses))
        winner = next(t for t in (a, b) if self.jobs(t))
        self.assertEqual(len(self.jobs(winner)), 2)
        self.assertEqual(self.c.get("/api/state").json["credits"], 0)
        self.assertEqual(self.approve(winner).status_code, 200)
        self.assertEqual(self.approve(winner, requestKey="different").status_code, 409)
        self.assertEqual(len(self.jobs(winner)), 2)

    def test_cancelled_queued_tasks_release_and_stale_callbacks_do_nothing(self):
        t = self.card()
        start = self.c.get("/api/state").json["credits"]
        with patch.object(studio.pool, "submit"):
            r = self.approve(t)
        self.assertEqual(r.status_code, 200, r.json)
        cancel = "agent/tasks/" + t["id"] + "/cancel"
        self.assertEqual(
            post(self.c, cancel, revision=t["revision"]).json["status"], "cancelled"
        )
        self.assertEqual(
            post(self.c, cancel, revision=t["revision"]).json["status"], "cancelled"
        )
        self.produce(t)
        self.assertEqual(self.c.get("/api/state").json["credits"], start)
        events = self.c.get("/api/agent/tasks/" + t["id"] + "/events").json["events"]
        self.assertEqual(
            [e["seq"] for e in events], sorted(set(e["seq"] for e in events))
        )
        self.assertEqual(
            self.c.get(
                "/api/agent/tasks/"
                + t["id"]
                + "/events?after="
                + str(events[-1]["seq"])
            ).json["events"],
            [],
        )

    def test_isolation_file_approval_event_project_and_archiving(self):
        t = self.card()
        stranger = studio.app.test_client()
        p = post(self.c, "agent/projects", title="店内活动").json["id"]
        mem = post(self.c, "agent/memory", name="名字", value="茶店").json["id"]
        for path in (
            "agent/conversations/" + self.cid,
            "agent/tasks/" + t["id"] + "/events",
            "agent/memory/" + mem,
        ):
            self.assertEqual(stranger.get("/api/" + path).status_code, 404)
        self.assertEqual(self.approve(t, stranger).status_code, 404)
        self.assertEqual(
            post(stranger, "agent/conversations", project=p).status_code, 404
        )
        with patch.object(studio.pool, "submit"):
            self.approve(t)
        self.c.delete("/api/agent/conversations/" + self.cid)
        self.assertEqual(
            self.c.get("/api/agent/conversations/" + self.cid).status_code, 404
        )
        self.assertEqual(
            self.c.get("/api/agent/tasks/" + t["id"] + "/events").json["task"][
                "status"
            ],
            "queued",
        )

    def test_real_export_revision_and_independent_failure_settlement(self):
        t = self.card()
        with patch.object(studio.pool, "submit"):
            self.approve(t)
        done = self.produce(t)
        self.assertEqual(done["status"], "delivered", done)
        copy, poster = done["items"]
        self.assertEqual(copy["text"], "下班来喝茶")
        with self.c.get(poster["download"]) as download:
            self.assertEqual(download.data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(
            post(
                self.c, "agent/tasks/" + t["id"] + "/cancel", revision=t["revision"]
            ).status_code,
            409,
        )
        edit = self.card("换一张")
        self.assertEqual(edit["workRef"], dict(id=poster["work"], version=1))
        self.assertEqual(edit["locked"]["title"], "下班来喝茶")
        with patch.object(studio.pool, "submit"):
            self.assertEqual(self.approve(edit).status_code, 200)
        revised = self.produce(edit)
        self.assertEqual(revised["status"], "delivered", revised)
        work = self.c.get("/api/works/" + poster["work"]).json
        self.assertEqual(work["current"], 2)
        self.assertEqual([v["title"] for v in work["versions"]], ["下班来喝茶"] * 2)
        start = self.c.get("/api/state").json["credits"]
        bad = self.card(action="new")
        with patch.object(studio.pool, "submit"):
            self.approve(bad)
        with patch.object(studio, "render", side_effect=ValueError("隔离回归的故障")):
            self.assertEqual(self.produce(bad)["status"], "failed")
        self.assertEqual(self.c.get("/api/state").json["credits"], start)
        self.assertEqual(self.detail()["tasks"][0]["status"], "delivered")

    def test_expired_quote_requires_refresh_with_exact_locked_copy(self):
        from itsdangerous.timed import TimestampSigner

        t = self.card()
        with patch.object(
            TimestampSigner, "get_timestamp", return_value=int(time.time()) + 1900
        ):
            self.assertEqual(self.approve(t).status_code, 400)
        self.assertEqual(self.jobs(t), [])
        renewed = self.card(
            "刷新报价", action="refresh", task=t["id"], revision=t["revision"]
        )
        self.assertNotEqual(t["quoteId"], renewed["quoteId"])
        self.assertEqual(t["locked"], renewed["locked"])
        self.assertEqual(self.approve(t).status_code, 409)

    def test_weekly_pause_and_natural_language_selection_only_make_quotes(self):
        topics = self.send("本周推荐")["messages"][-1]["items"]
        self.assertGreaterEqual(len(topics), 2)
        t = self.card("做第二个")
        self.assertEqual(t["request"], topics[1]["brief"])
        self.assertFalse(self.jobs(t))
        post(self.c, "agent/preferences", weeks=0)
        with studio.db(True) as c:
            c.execute(
                "UPDATE agent_preferences SET last_sent=? WHERE tenant=?",
                ("2020-01-01", self.tenant),
            )
        cid = self.conversation()
        self.assertEqual(self.detail(cid)["messages"], [])
        post(self.c, "agent/preferences", weeks=2)
        self.assertEqual(
            post(self.c, "agent/conversations/" + cid + "/visit").json["messages"][0][
                "kind"
            ],
            "topics",
        )

    def test_conflicting_project_price_requires_explicit_confirmation(self):
        pid = post(self.c, "agent/projects", title="本次推介").json["id"]
        post(self.c, "agent/memory", name="入场票价", value="48元", project=pid)
        cid = self.conversation(pid)
        t = self.card("做一张活动海报，入场票价68元，文案用「一起喝茶」", cid)
        self.assertEqual(t["status"], "waiting_input")
        self.assertIn("48元", t["note"])
        confirmed = self.card("本次以68元为准", cid)
        self.assertEqual(confirmed["status"], "quoted")
        self.assertNotIn("入场票价：48元", confirmed["facts"])
        self.assertEqual(
            self.c.get("/api/agent/memory?project=" + pid).json["entries"][0]["value"],
            "48元",
        )

    def test_new_video_uses_legacy_hook_and_approved_budget(self):
        request = dict(
            brief="制作一条茶馆短片，介绍新到的茶叶",
            ratio="story",
            duration=15,
            deliveryMode="video",
        )
        old = post(self.c, "creations/plan", **request).json
        t = self.card(request["brief"])
        self.assertEqual(t["cost"], old["cost"])
        with studio.db() as c:
            q = c.execute(
                "SELECT quote FROM agent_task WHERE id=?", (t["id"],)
            ).fetchone()[0]
        legacy = studio.quotes.loads(old["quote"])["items"][-1]["spec"]
        upgraded = studio.quotes.loads(q)["items"][-1]["spec"]
        self.assertEqual(upgraded["plan"]["skillPlan"], legacy["plan"]["skillPlan"])
        story = upgraded["replacement"]["storyboard"]
        self.assertEqual(story, legacy["replacement"]["storyboard"])
        self.assertEqual(story[0]["start"], 0)
        self.assertGreaterEqual(story[0]["end"], 2)
        self.assertEqual(story[-1]["end"], 15)
        self.assertEqual(upgraded["plan"]["capability"]["id"], "merchant.video")

    def test_video_and_poster_from_different_conversations_finish_independently(self):
        poster = self.card()
        second = self.conversation()
        video = self.card("给茶店做一条15秒短片，已有文案：来喝今晚的茶", second)
        with patch.object(studio.pool, "submit"):
            first = self.approve(poster)
            other = self.approve(video)
        self.assertEqual(first.status_code, 200, first.json)
        self.assertEqual(other.status_code, 200, other.json)
        with ThreadPoolExecutor(max_workers=2) as workers:
            list(workers.map(studio.produce, self.jobs(video) + self.jobs(poster)))
        actual = self.detail(second)["tasks"][0]
        self.assertEqual(actual["status"], "delivered", actual)
        self.assertEqual(self.detail()["tasks"][0]["status"], "delivered")
        with self.c.get(actual["items"][-1]["video"]) as media:
            self.assertIn(b"ftyp", media.data[:20])

    def test_followup_supplies_the_missing_subject_in_same_task(self):
        first = self.card("帮我做一张海报")
        self.assertEqual(first["status"], "waiting_input")
        updated = self.card("宣传桂花乌龙，已有文案：今天喝桂花茶")
        self.assertEqual(updated["id"], first["id"])
        self.assertEqual(updated["status"], "quoted")
        self.assertEqual(updated["locked"]["title"], "今天喝桂花茶")

    def test_price_edit_requotes_and_keeps_previous_approved_snapshot(self):
        first = self.card("为乌龙茶做海报，售价19元，文案用「喝杯乌龙只要19元」")
        changed = self.card("把19元改为29元")
        self.assertEqual(changed["locked"]["title"], "喝杯乌龙只要29元")
        self.assertNotIn("19元", "".join(changed["facts"]))
        self.assertEqual(self.approve(first).status_code, 409)
        with studio.db() as c:
            historical = c.execute(
                "SELECT locked FROM agent_revision WHERE task=? AND revision=?",
                (first["id"], first["revision"]),
            ).fetchone()[0]
            self.assertIn("19元", historical)

    def test_memorax_explicit_remember_forget_and_promo_price_guard(self):
        post(self.c, "agent/memory", name="招牌", value="桂花乌龙")
        r1 = self.send("记住：门店地址是綦江万达三楼")
        self.assertIn("已记入店铺长期记忆", r1["messages"][-1]["text"])
        r_dup = self.send("记住：门店地址是綦江万达三楼")
        self.assertIn("已经在册", r_dup["messages"][-1]["text"])
        promo = self.send("记住：今天活动价9.9元")
        self.assertIn("临时价格", promo["messages"][-1]["text"])
        entries = self.c.get("/api/agent/memory").json["entries"]
        self.assertFalse(any("9.9" in e["value"] for e in entries))
        t = self.card()
        recalled_names = [m["name"] for m in t["recalledMemories"]]
        self.assertIn("门店地址", recalled_names)
        self.assertIn("招牌", recalled_names)
        forgot = self.send("忘掉门店地址")
        self.assertIn("已忘掉记忆", forgot["messages"][-1]["text"])
        remaining = [e["name"] for e in self.c.get("/api/agent/memory").json["entries"]]
        self.assertEqual(remaining, ["招牌"])

    def test_memorax_candidate_extraction_confirm_dismiss_and_expiry(self):
        chat = self.send("我们店在合川宝龙广场二楼，帮我做一张海报，文案用「下班喝一杯」")
        candidates = chat["candidates"]
        self.assertTrue(any(c["name"] == "门店地址" for c in candidates), candidates)
        cand = next(c for c in candidates if c["name"] == "门店地址")
        self.assertEqual(cand["status"], "candidate")
        self.assertEqual(cand["active"], 0)
        self.assertNotIn("合川宝龙广场二楼", "".join(chat["tasks"][-1]["facts"]))
        res = post(self.c, "agent/memory/" + cand["id"] + "/confirm", version=cand["version"])
        self.assertEqual(res.status_code, 200)
        next_task = self.card(cid=self.conversation())
        self.assertIn("合川宝龙广场二楼", "".join(next_task["facts"]))
        expired = post(
            self.c,
            "agent/memory",
            name="冬季限定",
            value="红糖姜茶",
            expiresAt="2020-01-01",
        ).json
        self.assertTrue(expired["id"])
        after_expiry = self.card(cid=self.conversation())
        self.assertNotIn("红糖姜茶", "".join(after_expiry["facts"]))

    def test_memorax_compaction_summary_invalidation_and_selective_retrieval(self):
        mem = post(self.c, "agent/memory", name="营业时间", value="每天10点到22点").json
        t = self.card()
        for i in range(14):
            self.send(f"你好" if i % 2 == 0 else "我们再聊聊细节")
        ctx = self.c.get("/api/agent/conversations/" + self.cid + "/context").json
        compacted = ctx["layers"]["ephemeral"]["compacted"]
        self.assertIsNotNone(compacted)
        self.assertIn("下班来喝茶", "".join(compacted["decisions"]))
        self.assertEqual(ctx["layers"]["task"]["locked"]["title"], "下班来喝茶")
        # Cross-tenant context access is rejected
        stranger = studio.app.test_client()
        self.assertEqual(
            stranger.get("/api/agent/conversations/" + self.cid + "/context").status_code,
            404,
        )
        # Deleting memory invalidates compacted summaries immediately (PRD §23)
        self.c.delete("/api/agent/memory/" + mem["id"], json=dict(version=1))
        ctx_after = self.c.get("/api/agent/conversations/" + self.cid + "/context").json
        self.assertIsNone(ctx_after["layers"]["ephemeral"]["compacted"])
        # Selective retrieval caps & prioritizes relevant entries when memory exceeds budget
        for idx in range(10):
            post(self.c, "agent/memory", name=f"普通备注{idx}", value=f"常规说明{idx}")
        post(self.c, "agent/memory", name="抹茶拿铁配方", value="宇治抹茶配鲜奶")
        focused = self.card("为抹茶拿铁配方做一张海报，文案用「鲜奶抹茶」", cid=self.conversation())
        self.assertLessEqual(len(focused["recalledMemories"]), 8)
        self.assertIn("抹茶拿铁配方", [m["name"] for m in focused["recalledMemories"]])

    def test_capability_registry_and_admin_observability(self):
        caps = self.c.get("/api/agent/capabilities").json["capabilities"]
        ids = {c["id"] for c in caps}
        self.assertEqual(ids, {"merchant.copy", "merchant.poster", "merchant.video"})
        for cap in caps:
            self.assertIn("version", cap)
            self.assertIn("fallbackVersion", cap)
            self.assertIn("inputSchema", cap)
            self.assertIn("outputSchema", cap)
            self.assertIn("timeoutSeconds", cap)
            self.assertIn("costCap", cap)
            self.assertIn(cap["health"], ("healthy", "degraded"))

    def test_agent_quality_cliche_guard_duration_pacing_and_frictionless_promo(self):
        from server import prompt_agent, wenan

        # 1. Deterministic AI-cliché guard (0ms, respects merchant literal brief)
        self.assertIn("匠心打造", wenan.cliche_error("匠心打造这杯好茶", "做一张茶饮海报"))
        self.assertEqual(wenan.cliche_error("匠心打造这杯好茶", "我们要写匠心打造"), "")

        # 2. Simple price+time promo in Personal Agent skips bureaucratic terms interrogation
        promo = self.card("帮我做一张周末促销海报，丹东红颜草莓29.9元一盒，文案用「周末来吃丹东草莓」")
        self.assertEqual(promo["status"], "quoted", promo)

        # 3. Video prompt adapts to 15s / 30s / 45s with explicit 0-2s scroll-stopping hook
        video = self.card("做一条15秒茶馆短片，文案用「下班来喝茶」", action="new")
        self.assertEqual(video["status"], "quoted", video)
        with studio.db() as c:
            q = c.execute("SELECT quote FROM agent_task WHERE id=?", (video["id"],)).fetchone()[0]
        vspec = next(i["spec"] for i in studio.quotes.loads(q)["items"] if i["spec"]["kind"] == "video")
        vprompt = vspec["plan"]["promptBrief"]["prompts"]["video"]
        self.assertIn("0–2 秒", vprompt)
        self.assertIn("15 秒", vprompt)
        self.assertIn("10–15 秒", vprompt)
        vspec30 = {**vspec, "duration": 30, "plan": {**vspec["plan"], "output": {**vspec["plan"]["output"], "duration": 30}}}
        prompt_agent.optimize(vspec30, infer=False)
        self.assertIn("30 秒", vspec30["plan"]["promptBrief"]["prompts"]["video"])
        self.assertIn("23–30 秒", vspec30["plan"]["promptBrief"]["prompts"]["video"])

        # 4. Poster prompt adapts composition to ratio and injects anti-slop guardrails
        poster = self.card("做一张16:9横版茶饮海报，文案用「午后这一杯」", action="new")
        with studio.db() as c:
            q = c.execute("SELECT quote FROM agent_task WHERE id=?", (poster["id"],)).fetchone()[0]
        pspec = next(i["spec"] for i in studio.quotes.loads(q)["items"] if i["spec"]["kind"] == "poster")
        full = prompt_agent.full_poster_prompt(
            pspec["plan"],
            {**pspec["replacement"], "title": "午后这一杯", "visualIdea": "热气升起与侧光茶汤"},
        )
        self.assertIn("16:9 横版", full)
        self.assertIn("60/30/10", full)
        self.assertIn("塑料磨皮", full)
        self.assertIn("热气升起与侧光茶汤", full)

    def test_production_elevation_prewarm_cache_targeted_repair_and_social_tiers(self):
        from server import prompt_agent, visual_review

        # 1. Targeted repair classifier picks fastest valid action without blind redraws
        r_typo = visual_review.classify_repair(["文字与邻近背景对比不足"], {"status": "pass"}, has_generated_bg=True)
        self.assertEqual(r_typo["strategy"], "typography")
        self.assertFalse(r_typo["redrawBackground"])

        r_subj = visual_review.classify_repair(["商品局部颜色、文字或轮廓与原图不一致"], {"status": "fail", "reason": "包装偏移"}, has_generated_bg=True)
        self.assertEqual(r_subj["strategy"], "subject_restore")
        self.assertTrue(r_subj["fallbackOriginal"])
        self.assertFalse(r_subj["redrawBackground"])

        r_scene = visual_review.classify_repair([], {"status": "fail", "reason": "背景与商品光影割裂"}, has_generated_bg=True)
        self.assertEqual(r_scene["strategy"], "scene_redraw")
        self.assertTrue(r_scene["redrawBackground"])

        # 2. Multi-tier social-currency copy fields pass through task_view cleanly
        t = self.card("为茶店做一张海报", action="new")
        def rich_options(spec, tenant):
            return [
                {
                    **spec["replacement"],
                    "title": "下班这杯桂花茶，留给最想见的人",
                    "body": "鲜泡桂花乌龙 · 19元",
                    "cta": "下班顺路进店",
                    "angle": "顾客邀约",
                    "shareTo": "一起加班的同事",
                    "reply": "走，六点半门口见",
                    "socialPost": "忙了一天，最治愈的还是下班顺路喝一杯热桂花乌龙。你下班最想喊谁一起？今晚顺路来店里坐坐。",
                    "visualIdea": "黄昏暖侧光照在琥珀茶汤与杯口热气上",
                },
                {
                    **spec["replacement"],
                    "title": "刚出炉的桂花香，路过就会停脚",
                    "body": "手工桂花乌龙 · 19元",
                    "cta": "到店现泡",
                    "angle": "画面切入",
                },
            ]
        with patch("server.copy_choices.write_options", side_effect=rich_options):
            opts_task = post(self.c, "agent/tasks/" + t["id"] + "/options", revision=t["revision"]).json
        self.assertEqual(opts_task["options"][0]["angle"], "顾客邀约")
        self.assertEqual(opts_task["options"][0]["shareTo"], "一起加班的同事")
        self.assertIn("最想喊谁一起", opts_task["options"][0]["socialPost"])
        chosen = self.card("选第一组")
        self.assertEqual(chosen["locked"]["shareTo"], "一起加班的同事")
        self.assertIn("最想喊谁一起", chosen["locked"]["socialPost"])

        # 3. Post-approval Creative Director elevation runs only when text model is enabled
        with studio.db() as c:
            q = c.execute("SELECT quote FROM agent_task WHERE id=?", (chosen["id"],)).fetchone()[0]
        pspec = next(i["spec"] for i in studio.quotes.loads(q)["items"] if i["spec"]["kind"] == "poster")
        elevate_replies = [
            (
                {
                    "product": "茶店",
                    "style": "quiet-light",
                    "directions": {
                        "copy": "围绕下班碰面写一句自然邀约",
                        "image": "暖侧光落在玻璃茶杯边缘，留出右侧干净负空间承接主标题。",
                    },
                },
                "director-llm",
            ),
            ({"ok": True}, "reviewer-llm"),
        ]
        with patch("server.model.engine_name", return_value="director-llm"), patch(
            "server.model.ask", side_effect=elevate_replies
        ):
            elevated = prompt_agent.elevate_for_production(pspec, chosen["locked"])
        self.assertTrue(elevated)
        self.assertTrue(pspec["plan"]["promptBrief"]["elevated"])
        self.assertEqual(pspec["plan"]["promptBrief"]["engine"], "director-llm")
        self.assertIn("暖侧光", pspec["plan"]["posterArt"].get("modelConcept", ""))

        # 4. Preflight disk cache avoids duplicate vision calls after pre-warming
        from PIL import Image
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            asset_dir = Path(tmp)
            (asset_dir / "a1").mkdir()
            Image.new("RGB", (64, 64), (210, 180, 140)).save(asset_dir / "a1" / "original.png")
            vcfg = {"provider": "test-vis", "model": "vis-1", "url": "https://example.invalid/v1"}
            spec1 = {"asset": "a1", "kind": "poster", "plan": {"original": "抹茶拿铁海报", "facts": "", "profile": {}}}
            spec2 = {"asset": "a1", "kind": "poster", "plan": {"original": "抹茶拿铁海报", "facts": "", "profile": {}}}
            with patch("server.model.chat_request", return_value={"ok": True, "reason": "杯身清晰无遮挡"}) as chat_req:
                visual_review.preflight_with(vcfg, spec1, asset_dir)
                visual_review.preflight_with(vcfg, spec2, asset_dir)
            self.assertEqual(chat_req.call_count, 1)
            self.assertEqual(spec2["plan"]["sourceReview"]["reason"], "杯身清晰无遮挡")

    def test_infinite_parametric_editorial_layout_engine(self):
        from PIL import Image
        from server import wenan
        from server.layout_engine import (
            ALL_ARCHITECTURES,
            COLOR_BLOCK_ARCHITECTURES,
            FULL_BLEED_ARCHITECTURES,
            PROTECTED_ARCHITECTURES,
            choose_recipe,
            compose_editorial_poster,
        )
        from server.typography import Typesetter

        # hiccai-wenan v4.4.0 social-currency & commercial closure guardrails
        self.assertEqual(wenan.VERSION, "4.4.0")
        self.assertTrue(wenan.broadcast_error("下班路过带盒红颜草莓回家"))
        self.assertEqual(wenan.broadcast_error("一人吃一半，别抢中间那颗"), "")
        fruit_plan = {"original": "主推丹东红颜草莓，现摘现发29.9元/盒，周末促销海报", "kind": "poster", "autoCreation": True}
        self.assertTrue(wenan.wants_social_currency(fruit_plan))
        self.assertIn(wenan.SHARING, wenan.sections(fruit_plan))
        self.assertIn(wenan.ACTION_CLOSING, wenan.sections(fruit_plan))

        hero = Image.new("RGB", (900, 1200), (195, 42, 46))
        ts = Typesetter()
        copy = {
            "title": "一人吃一半，别抢中间那颗",
            "body": "丹东现摘直发，29.9元/盒尝鲜",
            "cta": "周末两天到店自取",
            "offer": "29.9元/盒",
        }
        archs, splits, ornaments, tastes = set(), set(), set(), set()
        for idx in range(220):
            r = choose_recipe((1080, 1440), f"fruit-seed-{idx}")
            archs.add(r["architecture"])
            splits.add(r["split"])
            ornaments.add(r["ornament"])
            tastes.add(r["taste"])
        self.assertEqual(len(archs), len(ALL_ARCHITECTURES))
        self.assertGreaterEqual(len(ALL_ARCHITECTURES), 20)
        self.assertGreaterEqual(len(FULL_BLEED_ARCHITECTURES), 6)
        self.assertGreaterEqual(len(COLOR_BLOCK_ARCHITECTURES), 4)
        self.assertGreaterEqual(len(splits), 25)
        self.assertGreaterEqual(len(ornaments), 5)
        self.assertGreaterEqual(len(tastes), 4)

        # Protected real merchant photo never uses cropping architectures
        for idx in range(20):
            r_prot = choose_recipe((1080, 1440), f"protected-{idx}", protected_subject=True)
            self.assertIn(r_prot["architecture"], PROTECTED_ARCHITECTURES)

        # End-to-end render succeeds across all 12 families and 4 aspect ratios with >= 7.0:1 title contrast
        for dims in ((960, 1280), (1280, 720), (900, 1600), (1080, 1080)):
            for arch in ALL_ARCHITECTURES:
                scene, layer, box, rec = compose_editorial_poster(
                    dims, hero, ts, "果小鲜水果铺  创意场景示意", copy, seed_text=f"dim-{dims}-{arch}", architecture=arch
                )
                self.assertEqual(scene.size, dims)
                self.assertEqual(layer.size, dims)
                self.assertIsNotNone(box)
                self.assertGreaterEqual(rec["titleContrast"], 7.0)
                self.assertGreaterEqual(rec["bodyContrast"], 4.5)
