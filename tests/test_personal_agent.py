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
