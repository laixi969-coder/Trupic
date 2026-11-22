"""Versioned local method library; reserved methods are never executable routes."""

import copy
import json
from pathlib import Path

from .design import visual_requests

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / ".agents/skills/trupic-creative-library/references/catalog.json"
)
CATALOG = json.loads(CATALOG_PATH.read_text())["skills"]
BY_ID = {item["id"]: item for item in CATALOG}


def catalog():
    return copy.deepcopy(CATALOG)


def snapshot(ids):
    selected = [BY_ID[key] for key in dict.fromkeys(ids)]
    if any(item["status"] == "reserve" for item in selected):
        raise ValueError("该技能目前只储备方法，尚未接入成品生成。")
    return {
        "version": 1,
        "skills": [
            {
                k: copy.deepcopy(item[k])
                for k in ("id", "name", "version", "source", "status")
            }
            for item in selected
        ],
        "instructions": {
            stage: [
                item["instructions"][stage]
                for item in selected
                if item["instructions"][stage]
            ]
            for stage in ("copy", "image", "video", "qa")
        },
        "limits": [item["limits"] for item in selected],
    }


def attach(plan, kind, workflow=None):
    if workflow:
        ids = [workflow]
        if workflow in ("launch", "promotion", "social", "live", "motion"):
            ids.insert(0, "poster_design")
        if kind == "video":
            ids.append("video_storyboard")
    else:
        ids = ["poster_design"] if kind in ("poster", "video") else []
        if kind == "video":
            ids.append("video_storyboard")
        if kind == "poster":
            brief = visual_requests(plan.get("original", "")).lower()
            ids.extend(
                item["id"]
                for item in CATALOG
                if item["status"] == "integrated"
                and any(word.lower() in brief for word in item["match"])
            )
    plan["skillPlan"] = snapshot(ids)
    return plan["skillPlan"]
