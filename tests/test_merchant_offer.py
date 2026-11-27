"""Regressions for signed weekday prices, readback faults and scoped revisions."""

import copy
import unittest

from server import merchant_offer as offers


class MerchantOfferTests(unittest.TestCase):
    def setUp(self):
        self.offer = offers.confirmed_offer(
            "抹茶拿铁，周五到店价18.90元。", "", "抹茶拿铁"
        )

    def test_merchant_sources_and_unambiguous_dates(self):
        self.assertEqual("到店", self.offer["channel"])
        reverse = offers.confirmed_offer(
            "做一条15秒短片。", "18.90元，仅限星期五", "抹茶拿铁"
        )
        self.assertEqual(
            {k: v for k, v in self.offer.items() if k != "channel"}, reverse
        )
        for text in (
            "周五拍一条15秒视频，杯子重19克。",
            "例如周五价19元。",
            "不是周五价19元。",
        ):
            self.assertIsNone(offers.confirmed_offer(text, "", "抹茶拿铁"))
        with self.assertRaisesRegex(ValueError, "多组"):
            offers.confirmed_offer("周五价18.90，周六价23。", "", "抹茶拿铁")

    def test_signed_version_edit_and_old_day_guards(self):
        from server.revisions import edit_request

        spec = {
            "plan": {
                "merchantOffer": self.offer,
                "facts": "周五活动价18.90元",
                "coordination": {"merchantOffer": self.offer},
                "profile": {"facts": "仅限周五"},
            }
        }
        draft = {
            "title": "看看杯壁。",
            "body": "杯壁两种颜色。",
            "detailLine": "杯壁两种颜色。",
            "cta": "周五到店，18.90元。",
        }
        base = copy.deepcopy((spec, draft))
        edit_request(spec, draft, "周五价从 18.90 改成 19.90", None)
        self.assertEqual("周五到店，19.90元。", draft["cta"])
        self.assertEqual(
            "19.90", spec["plan"]["coordination"]["merchantOffer"]["amount"]
        )
        self.assertEqual(base[1]["title"], draft["title"])
        self.assertEqual("18.90", self.offer["amount"])
        for change in ("周六价从19.90改成23", "周五价从18.90改成23"):
            with self.assertRaisesRegex(ValueError, "不符"):
                edit_request(spec, draft, change, None)

    def test_refresh_price_before_approval_updates_line_but_not_measured_equipment(
        self,
    ):
        from server.agent_planner import correct_price

        values = {
            "brief": "周五价18.9",
            "facts": "周五价18.9，尺寸18.90厘米",
            "ownCopy": "周五到店，¥18.90。",
        }
        locked = {"cta": "周五到店，¥18.90。"}
        self.assertTrue(correct_price(values, locked, "周五价从18.90改成19.90"))
        self.assertEqual(locked["cta"], values["ownCopy"])
        self.assertIn("周五价19.90", values["brief"])
        self.assertIn("18.90厘米", values["facts"])

    def test_verified_price_is_visible_in_the_approved_script(self):
        from server.agent_planner import provided_copy

        draft = {"title": "看看。", "detailLine": "有分层。", "cta": "到店试试。"}
        with self.assertRaisesRegex(ValueError, "定稿中写明"):
            offers.bind_script(draft, self.offer, supplied=True)
        offers.bind_script(draft, self.offer)
        self.assertEqual("周五到店18.90元。", draft["cta"])
        quote = {
            "items": [
                {"spec": {"plan": {"productNarration": True}, "replacement": {}}}
            ],
            "shared": {"merchantOffer": self.offer},
        }
        with self.assertRaises(ValueError):
            provided_copy("看看。\n有分层。\n周五到店，19.90元。", quote)

    def test_independent_audio_price_and_weekday(self):
        cases = (
            "周五到店十八块九",
            "星期五到店一杯十八元九角",
            "周五到店,18.90元",
            "周五到店十八点九元",
        )
        for transcript in cases:
            offers.require_facts(transcript, self.offer, "成片", audio=True)
        for bad in (
            "周六到店十八块九",
            "周五到店十八块八",
            "周五十八块九、十九块九",
            "周五十八块",
        ):
            with self.assertRaises(ValueError):
                offers.require_facts(bad, self.offer, "成片", audio=True)
        self.assertEqual("周五十八块九。", offers.spoken_prices("周五18.90元。"))
        self.assertEqual("周五十九块零五分。", offers.spoken_prices("周五¥19.05。"))

    def test_matching_price_in_a_negation_or_other_currency_never_passes(self):
        wrong = (
            "周五不到店18.90元",
            "周五到店不是18.90元",
            "18.90元到店，周五不适用",
            "周五到店18.90美元",
            "周五到店18.90元起",
            "周五到店十八块九，美元结算",
        )
        for phrase in wrong:
            for audio in (True, False):
                with self.assertRaises(ValueError, msg=phrase):
                    offers.require_facts(phrase, self.offer, "交付", audio=audio)
        with self.assertRaises(ValueError):
            offers.require_facts("周五活动价18.90元", self.offer, "适用渠道")
        self.assertIsNone(offers.confirmed_offer("周五到店价18.90美元", "", "抹茶"))

    def test_reject_visible_wrong_digits_and_uncertain_price(self):
        rows = [
            {"text": "周五到店价", "confidence": 0.99},
            {"text": "￥18.90", "confidence": 0.93},
        ]
        offers._verify_readings(rows, self.offer, "海报")
        for invalid in ("￥19.90", "¥18.09", "￥18.901"):
            with self.assertRaises(ValueError):
                offers._verify_readings(
                    [rows[0], dict(rows[1], text=invalid)], self.offer, "海报"
                )
        with self.assertRaisesRegex(ValueError, "清晰度"):
            offers._verify_readings(
                [rows[0], dict(rows[1], confidence=0.35)], self.offer, "海报"
            )
