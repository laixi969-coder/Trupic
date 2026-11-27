"""Merchant feedback joins real deliveries to settled usage and hides both sides until voting."""

import json
import sqlite3
from collections import Counter
from unittest import TestCase
from unittest.mock import patch

from test_workflows import post, studio


class MerchantBlindTests(TestCase):
    def setUp(self):
        self.c = studio.app.test_client()
        self.tenant = self.c.get("/api/state").json["workspace"]
        self.work = studio.ident()
        with studio.db(True) as c:
            c.execute(
                "INSERT INTO work VALUES(?,?,?,?,?)",
                (self.work, self.tenant, "video", 1, studio.now()),
            )
        self.add_version(1, "18.90", companion=True)

    def add_version(self, n, amount, companion=False, receipt=True):
        run, task, job = studio.ident(), studio.ident(), studio.ident()
        t = self.tenant
        day = f"2026-01-{n:02d}"
        plan = {
            "agentTask": task,
            "creationRun": run,
            "merchantOffer": {"amount": amount, "weekday": "周五"},
        }
        with studio.db(True) as c:
            c.execute(
                "INSERT INTO agent_task(id,tenant,conversation,status,revision,input,run,created) VALUES(?,?,?,?,?,?,?,?)",
                (
                    task,
                    t,
                    "fixture",
                    "delivered",
                    1,
                    "{}",
                    run,
                    day + "T10:00:00+00:00",
                ),
            )
            jobs = []
            for direct, debit in [
                (True, 10 if n == 1 else 1),
                (False, 2 if n == 1 and companion else 0),
            ]:
                jid = job if direct else studio.ident()
                c.execute(
                    """INSERT INTO job(id,tenant,request_key,spec,state,cost,work,version,created)
                          VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        jid,
                        t,
                        jid,
                        studio.dump({"plan": plan}),
                        "complete",
                        debit,
                        self.work if direct else studio.ident(),
                        n,
                        day + "T10:00:15+00:00",
                    ),
                )
                if debit and receipt:
                    c.execute(
                        "INSERT INTO ledger(tenant,job,delta,note,created) VALUES(?,?,?,'测试',?)",
                        (t, jid, -debit, day + "T10:00:35+00:00"),
                    )
                jobs.append({"job": jid})
            c.execute(
                "INSERT INTO creative_run VALUES(?,?,?,?,?,?,?,?)",
                (run, t, run, "", "", "{}", studio.dump(jobs), day + "T10:00:15+00:00"),
            )
            c.execute(
                "INSERT INTO version VALUES(?,?,?,?,?,?)",
                (
                    self.work,
                    n,
                    studio.dump({"plan": plan}),
                    studio.dump({"title": "抹茶拿铁"}),
                    "[]",
                    day + "T10:00:35+00:00",
                ),
            )
            c.execute("UPDATE work SET current=? WHERE id=?", (n, self.work))
        directory = studio.DATA / t / "works" / self.work / str(n)
        directory.mkdir(parents=True)
        (directory / "video.mp4").write_bytes(b"anonymous-video" + bytes([n]))

    def create(self, n, source="merchant"):
        result = post(
            self.c,
            "agent/blind-reviews",
            briefId="food-01",
            work=self.work,
            revisionVersion=n,
            source=source,
        )
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def vote(self, case, **fields):
        return post(self.c, "agent/blind-reviews/" + case["id"] + "/answer", **fields)

    def summary(self):
        return self.c.get("/api/agent/blind-reviews").json["summary"]

    def test_catalog_creation_drafts_cover_all_three_sectors_and_current_terms(self):
        from server.agent_planner import explicit_kind

        response = self.c.get("/api/agent/blind-briefs")
        self.assertEqual(response.status_code, 200)
        rows = response.json["briefs"]
        self.assertEqual(
            Counter(b["sector"] for b in rows),
            {"food": 12, "retail": 12, "service": 12},
        )
        self.assertEqual(
            {b["id"] for b in rows},
            {
                f"{sector}-{i:02d}"
                for sector in ("food", "retail", "service")
                for i in range(1, 13)
            },
        )
        for b in rows:
            with self.subTest(brief=b["id"]):
                self.assertEqual(b["provenance"], "authored_fixture")
                draft = b["creationDraft"]
                self.assertEqual(explicit_kind(draft), b["kind"])
                for value in [
                    b["brief"],
                    b["facts"]["product"],
                    *b["facts"]["conditions"],
                    *b["avoid"],
                ]:
                    self.assertIn(value, draft)
                if b["id"] == "food-01":
                    self.assertIn("周五到店价19.90元", draft)
                    self.assertNotIn("18.90", draft)
                else:
                    self.assertIn(b["facts"]["offer"], draft)

    def test_pair_preferences_follow_both_clients_for_all_ratings(self):
        valid_choices = (
            (True, False, {"A"}),
            (False, True, {"B"}),
            (False, False, {"neither"}),
            (True, True, {"A", "B", "tie"}),
        )
        n = 1
        for a, b, choices in valid_choices:
            ratings = {
                s: {"publish": can_post, "reason": "" if can_post else "口播听不清。"}
                for s, can_post in [("A", a), ("B", b)]
            }
            for selected in sorted(choices):
                n += 1
                self.add_version(n, "18.90")
                case = self.create(n)
                for invalid in {"A", "B", "tie", "neither"} - choices:
                    with self.subTest(a=a, b=b, invalid=invalid):
                        self.assertEqual(
                            self.vote(
                                case, ratings=ratings, preference=invalid
                            ).status_code,
                            400,
                        )
                self.assertEqual(
                    self.vote(case, ratings=ratings, preference=selected).status_code,
                    200,
                )
        foreign = studio.app.test_client()
        path = "/api/agent/blind-reviews/" + case["id"] + "/answer"
        self.assertEqual(
            foreign.post(
                path, json={"ratings": ratings, "preference": selected}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.c.post(
                path,
                json={"ratings": ratings, "preference": selected},
                headers={"Origin": "https://external.example"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.vote(case, ratings={}, preference="unknown").status_code, 409
        )

    def test_selected_same_price_revisions_exclude_v1_and_first_draft_statistics(self):
        self.add_version(2, "19.90")
        self.add_version(3, "19.90")
        def pair(base):
            return post(self.c, "agent/blind-reviews", briefId="food-01",
                        work=self.work, baseVersion=base, revisionVersion=3)

        for invalid in [0, 3, 4, True, 2.5, "2"]:
            self.assertEqual(pair(invalid).status_code, 400)
        same_end = self.create(3)
        case = pair(2).json
        self.assertNotEqual(same_end["id"], case["id"])
        self.assertEqual(case, pair(2).json)
        self.assertFalse({"baseVersion", "revisionVersion", "baseSlot", "visualEngine"} & case.keys())
        fetched = []
        for option in case["options"]:
            with self.c.get(option["url"]) as media:
                fetched.append(media.data[-1])
        self.assertEqual(sorted(fetched), [2, 3])
        answer = {"preference": "tie", "ratings": {s: {"publish": True} for s in ("A", "B")}}
        result = self.vote(case, **answer).json["reveal"]
        self.assertEqual(result["versions"][result["baseSlot"]]["version"], 2)
        self.assertEqual(result["versions"][result["revisionSlot"]]["version"], 3)
        self.assertEqual(result["factChanges"], [])
        self.assertEqual(result["firstDraftEvidence"], "no_first_draft")
        self.assertIsNone(result["firstDraftSlot"])
        self.assertIsNone(result["firstDraftPublish"])
        stats = self.summary()
        self.assertEqual((stats["issued"], stats["answered"], stats["firstDraftResponses"]), (2, 1, 0))

    def test_migrating_existing_ballots_keeps_ids_answers_and_distinct_pairs(self):
        with sqlite3.connect(":memory:") as c:
            c.execute("""CREATE TABLE merchant_blind_review (
                id TEXT PRIMARY KEY, tenant TEXT, work TEXT, revision_version INTEGER,
                source TEXT, kind TEXT, brief TEXT, slots TEXT, created TEXT,
                submitted TEXT, answer TEXT, result TEXT, UNIQUE(tenant,work,revision_version,source))""")
            old = ("old", "tenant", "work", 3, "demo", "video", "{}", '{"A":3,"B":1}',
                   "created", "submitted", "answer", "result")
            c.execute("INSERT INTO merchant_blind_review VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", old)
            for _ in range(2):
                studio.merchant_blind.ensure_schema(c)
            self.assertEqual(c.execute("SELECT base_version,id,slots,answer,result FROM merchant_blind_review").fetchone(),
                             (1, "old", old[7], "answer", "result"))
            select = """INSERT INTO merchant_blind_review
                      SELECT ?,tenant,work,?,revision_version,source,kind,brief,slots,created,submitted,answer,result
                      FROM merchant_blind_review WHERE id='old'"""
            c.execute(select, ("new", 2))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute(select, ("duplicate", 2))

    def test_blind_media_stable_private_ranged_blocked_on_trash_and_atomic_answer(self):
        self.add_version(2, "19.90")
        with patch.object(studio.merchant_blind.secrets, "randbelow", return_value=1):
            case = self.create(2, source="demo")
        self.assertEqual(case, self.create(2, source="demo"))
        self.assertIsNone(case["reveal"])
        self.assertNotIn(self.work, json.dumps(case))
        self.assertNotIn("facts", case["brief"])
        self.assertEqual([o["slot"] for o in case["options"]], ["A", "B"])
        url = case["options"][0]["url"]
        with self.c.get(url, headers={"Range": "bytes=1-4"}) as response:
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.data, b"nony")
            self.assertIn("A.mp4", response.headers["Content-Disposition"])
            self.assertNotIn("Last-Modified", response.headers)
        other = studio.app.test_client()
        self.assertEqual(other.get(url).status_code, 404)
        self.assertEqual(
            other.get("/api/agent/blind-reviews/" + case["id"]).status_code, 404
        )
        self.assertEqual(
            self.vote(
                case,
                ratings={"A": {"publish": False}, "B": {"publish": True}},
                preference="B",
            ).status_code,
            400,
        )
        valid = {
            "preference": "B",
            "ratings": {
                "A": {"publish": False, "reason": "语调过快"},
                "B": {"publish": True, "reason": ""},
            },
            "merchantEditMinutes": 2.5,
        }
        done = self.vote(case, **valid)
        self.assertEqual(done.status_code, 200, done.json)
        revealed = done.json["reveal"]
        self.assertEqual(revealed["firstDraftSlot"], "B")
        self.assertEqual(revealed["firstDraftEvidence"], "changed_facts")
        self.assertEqual(
            revealed["factChanges"],
            [{"field": "amount", "before": "18.90", "after": "19.90"}],
        )
        self.assertEqual(revealed["versions"]["A"]["credits"], 1)
        self.assertEqual(revealed["versions"]["B"]["credits"], 12)
        self.assertEqual(revealed["versions"]["B"]["workCredits"], 10)
        self.assertEqual(revealed["versions"]["A"]["productionSeconds"], 20)
        self.assertEqual(revealed["versions"]["A"]["requestToDeliverySeconds"], 35)
        self.assertEqual(revealed["merchantEditMinutes"], 2.5)
        self.assertEqual(self.vote(case, **valid).json, done.json)
        self.assertEqual(
            self.vote(case, **{**valid, "preference": "tie"}).status_code, 409
        )
        self.assertEqual(self.summary()["answered"], 0)
        with studio.db(True) as c:
            c.execute(
                "INSERT INTO work_trash VALUES(?,?,?,?)",
                (self.work, self.tenant, "batch", studio.now()),
            )
        self.assertEqual(self.c.get(url).status_code, 404)

    def test_single_first_draft_is_independent_of_later_preference_and_counts_once(
        self,
    ):
        single = self.create(1)
        self.assertEqual(len(single["options"]), 1)
        feedback = self.vote(
            single, ratings={"A": {"publish": False, "reason": "没有说清到店条件。"}}
        ).json["reveal"]
        self.assertIsNone(feedback["revisionSlot"])
        self.assertEqual(feedback["firstDraftEvidence"], "at_first_delivery")
        self.add_version(2, "18.90")
        pair = self.create(2)
        self.vote(
            pair, preference="A", ratings={s: {"publish": True} for s in ("A", "B")}
        )
        totals = self.summary()
        self.assertEqual(
            (
                totals["issued"],
                totals["answered"],
                totals["firstDraftResponses"],
                totals["firstDraftPublish"],
            ),
            (2, 2, 1, 0),
        )
        self.assertEqual(totals["bySector"]["food"]["responseRate"], 1)
        with studio.db(True) as c:
            c.execute("UPDATE agent_task SET run=NULL WHERE tenant=?", (self.tenant,))
        self.add_version(3, "22.00", receipt=False)
        second = self.create(3)
        result = self.vote(
            second, preference="tie", ratings={s: {"publish": True} for s in ("A", "B")}
        ).json["reveal"]
        first = result["versions"][result["firstDraftSlot"]]
        self.assertIsNone(first["requestToDeliverySeconds"])
        self.assertIsNone(result["versions"][result["revisionSlot"]]["credits"])
        self.assertEqual(self.summary()["excludedFactChanged"], 1)
