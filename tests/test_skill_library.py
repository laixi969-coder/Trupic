"""Skill routing honors media, negation and executable capability boundaries."""

import unittest

from server.skill_library import attach, catalog, snapshot
from server.skill_catalog import SKILLS


class SkillLibraryTests(unittest.TestCase):
    def test_poster_and_video_methods_are_selected_without_user_skill_choice(self):
        plan = {"original": "给新品做一张封面，不要横幅"}
        result = attach(plan, "poster")
        selected = {item["id"] for item in result["skills"]}
        self.assertIn("poster_design", selected)
        self.assertIn("cover_design", selected)
        self.assertNotIn("banner_design", selected)
        self.assertEqual(attach(plan, "copy")["skills"], [])
        selected = {item["id"] for item in attach(plan, "video")["skills"]}
        self.assertEqual(selected, {"poster_design", "video_storyboard"})

    def test_reserves_cannot_be_submitted_as_execution_plans(self):
        for item in catalog():
            if item["status"] == "reserve":
                with self.subTest(skill=item["id"]):
                    with self.assertRaises(ValueError):
                        snapshot([item["id"]])
                    selected = attach({"original": item["name"]}, "poster")
                    self.assertNotIn(item["id"], [s["id"] for s in selected["skills"]])

    def test_snapshots_preserve_revision_and_do_not_mutate_library(self):
        first = snapshot(["poster_design"])
        first["skills"][0]["version"] = "changed"
        first["instructions"]["image"][0] = "changed"
        second = snapshot(["poster_design"])
        self.assertNotEqual(first, second)
        self.assertTrue(second["instructions"]["copy"])
        self.assertTrue(second["instructions"]["image"])
        self.assertFalse(second["skills"][0]["source"]["definitionAvailable"])
        workflows = {
            row["workflow"] for row in catalog() if row["status"] == "workflow"
        }
        self.assertEqual(workflows, set(SKILLS))
