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


def catalog(c=None):
    items = copy.deepcopy(CATALOG)
    if c is not None:
        for item in items:
            versions = c.execute(
                "SELECT * FROM skill_version WHERE skill=? ORDER BY n DESC",
                (item["id"],),
            )
            item["versions"] = []
            for row in versions:
                version = dict(
                    row,
                    instructions=json.loads(row["instructions"]),
                    tests=json.loads(row["tests"]),
                )
                item["versions"].append(version)
                if version["status"] == "live":
                    item.update(
                        version=f"{item['version']}+{version['n']}",
                        instructions=version["instructions"],
                    )
    return items


def snapshot(ids, overrides=None):
    selected = [BY_ID[key] for key in dict.fromkeys(ids)]
    if any(item["status"] == "reserve" for item in selected):
        raise ValueError("该技能目前只储备方法，尚未接入成品生成。")
    selected = [(overrides or {}).get(item["id"], item) for item in selected]
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


def effective_versions(c, tenant):
    from .creative import uidnum

    pilot = uidnum(tenant) % 100 < 10
    result = {}
    for row in c.execute(
        "SELECT * FROM skill_version WHERE status IN ('live','pilot') ORDER BY (status='pilot')"
    ):
        if row["status"] == "pilot" and not pilot:
            continue
        base = BY_ID[row["skill"]]
        result[base["id"]] = dict(
            base,
            version=f"{base['version']}+{row['n']}",
            instructions=json.loads(row["instructions"]),
        )
    return result


def manage_version(c, actor, data):
    from .creative import RISK, UNKNOWN, draft_copy, prepare
    from .prompt_agent import optimize
    from .store import audit, dump, now

    skill = data.get("id")
    if (
        not isinstance(skill, str)
        or skill not in BY_ID
        or BY_ID[skill]["status"] == "reserve"
    ):
        raise ValueError("请选择已接入的技能。")
    base = BY_ID[skill]
    action = data.get("action")
    if action == "test":
        reason, instructions = data.get("reason"), data.get("instructions")
        stages = base["instructions"]
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 220
            or not isinstance(instructions, dict)
            or set(instructions) != set(stages)
        ):
            raise ValueError("请填写更新原因和各阶段的方法。")
        if any(
            not isinstance(v, str)
            or len(v) > 900
            or (bool(stages[k]) and not v.strip())
            for k, v in instructions.items()
        ):
            raise ValueError("已接入阶段的方法不能为空，每项最多 900 字。")
        instructions = {k: v.strip() for k, v in instructions.items()}
        live = c.execute(
            "SELECT instructions FROM skill_version WHERE skill=? AND status='live'",
            (skill,),
        ).fetchone()
        current = json.loads(live[0]) if live else stages
        if current == instructions:
            raise ValueError("请先修改至少一项创作指导。")
        tests = [
            {
                "name": "真实性门槛",
                "ok": not any(
                    RISK.search(v) or UNKNOWN.search(v) for v in instructions.values()
                ),
            }
        ]
        candidate = dict(base, instructions=instructions)
        for brief, kind in (
            ("为台球室制作周末邀约海报", "poster"),
            ("用奶茶照片做一条上新短片", "video"),
            ("给火锅店老客写一封邀请", "copy"),
        ):
            plan = prepare(
                brief,
                {},
                [],
                {"id": "baseline", "method": "moment", "name": "固定测试"},
            )
            samples = []
            for variant in (dict(base, instructions=current), candidate):
                trial = copy.deepcopy(plan)
                trial["skillPlan"] = snapshot([skill], {skill: variant})
                optimize({"plan": trial, "kind": kind, "asset": ""}, infer=False)
                prompts = trial["promptBrief"]["prompts"]
                samples.append(prompts)
                if variant is candidate:
                    cp = draft_copy(trial)
                    ok = bool(cp["title"] and cp["body"]) and all(
                        instructions[k] in v for k, v in prompts.items()
                    )
            tests.append(
                {
                    "name": brief,
                    "ok": ok,
                    "changed": [k for k in prompts if samples[0][k] != samples[1][k]],
                }
            )
        n = c.execute(
            "SELECT COALESCE(MAX(n),0)+1 FROM skill_version WHERE skill=?", (skill,)
        ).fetchone()[0]
        c.execute(
            "INSERT INTO skill_version VALUES(?,?,?,?,?,?,?,NULL)",
            (
                skill,
                n,
                dump(instructions),
                reason.strip(),
                dump(tests),
                "tested" if all(t["ok"] for t in tests) else "failed",
                now(),
            ),
        )
    elif action in ("pilot", "release", "rollback"):
        n = data.get("n")
        if type(n) is not int or n < 0 or (not n and action != "rollback"):
            raise ValueError("请选择要启用的版本。")
        if n:
            row = c.execute(
                "SELECT tests,status FROM skill_version WHERE skill=? AND n=?",
                (skill, n),
            ).fetchone()
            if (
                not row
                or row["status"] == "failed"
                or not all(t["ok"] for t in json.loads(row["tests"]))
            ):
                raise ValueError("此版本没有通过固定测试。")
            if action == "pilot" and row["status"] == "live":
                raise ValueError("此版本已全量启用。")
        if action == "pilot":
            c.execute(
                "UPDATE skill_version SET status='archived' WHERE skill=? AND status='pilot'",
                (skill,),
            )
        else:
            c.execute(
                "UPDATE skill_version SET status='archived' WHERE skill=? AND status IN ('live','pilot')",
                (skill,),
            )
        if n:
            c.execute(
                "UPDATE skill_version SET status=?,published=? WHERE skill=? AND n=?",
                ("pilot" if action == "pilot" else "live", now(), skill, n),
            )
    else:
        raise ValueError("请选择有效的版本操作。")
    audit(
        c,
        actor,
        {
            "test": "固定测试技能",
            "pilot": "灰度发布技能",
            "release": "发布技能",
            "rollback": "回退技能",
        }[action],
        f"{skill} · {n}",
    )


def attach(plan, kind, workflow=None, overrides=None):
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
    plan["skillPlan"] = snapshot(ids, overrides)
    return plan["skillPlan"]
