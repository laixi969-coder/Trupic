"""Deliver two real matcha campaign versions through the HTTP assistant and verify the quoted revision."""

import argparse
from collections import Counter
from functools import partial
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import time
import uuid
import wave
from zipfile import ZipFile

import requests

ROOT = Path(__file__).resolve().parents[1]
PROOF = runpy.run_path(str(ROOT / "scripts/proof-product-film.py"))
DEST = ROOT / "docs/research/video-integration/matcha-friday-revision"
BRIEF = "用这张抹茶拿铁商品图做15秒竖屏口播短片、活动海报和发布配文。周五到店价18.90元。开头和中段温和介绍。"
LINES = ["这一杯，先别搅。", "你看，抹茶和牛奶分了层。", "周五到店，18.90元。"]
EDIT = "周五价从18.90元改成19.90元，保留原画面，只把片尾换成轻快口吻。"


def new_key():
    return uuid.uuid4().hex


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def task_route(card):
    return "/api/agent/tasks/" + card["id"]


def approve(get, post, card):
    route = task_route(card)
    wallet = get("/api/state").json()
    payload = dict(
        approvalType="production",
        revision=card["revision"],
        quoteId=card["quoteId"],
        confirmedCost=card["cost"],
        requestKey=new_key(),
    )
    first = post(route + "/approve", json=payload).json()
    replay = post(route + "/approve", json=payload).json()
    jobs = [i["job"] for i in first["items"]]
    assert jobs and jobs == [i["job"] for i in replay["items"]]
    until = time.monotonic() + 550
    last_status = None
    while True:
        response = get(route + "/events").json()
        task = response["task"]
        status = (
            task["status"],
            [(i.get("state"), i.get("stage")) for i in task.get("items", [])],
        )
        if last_status != status:
            print(card["id"], status, flush=True)
            last_status = status
        if task["status"] == "delivered":
            break
        if time.monotonic() >= until or task["status"] in ("cancelled", "failed"):
            raise RuntimeError(str(task["items"]))
        time.sleep(0.4)
    delivered_jobs = [
        i["job"] for i in post(route + "/approve", json=payload).json()["items"]
    ]
    assert jobs == delivered_jobs
    after = get("/api/state").json()
    ledgers = [
        r for r in after["ledger"] if r not in wallet["ledger"] and r["delta"] < 0
    ]
    holds = [r for r in after["reservations"] if r not in wallet["reservations"]]
    totals = Counter()
    for h in holds:
        totals[h["action"]] += h["amount"]
    assert (
        wallet["credits"] - after["credits"]
        == card["cost"]
        == -sum(i["delta"] for i in ledgers)
    )
    assert totals == {"reserve": card["cost"], "consume": card["cost"]}, (totals, card)
    assert sum(e["type"] == "reserved" for e in response["events"]) == 1
    proof = dict(
        quoted=card["cost"],
        before=wallet["credits"],
        after=after["credits"],
        jobs=jobs,
        identicalJobIdsOnThreeSubmissions=True,
        reservations=holds,
        debits=ledgers,
    )
    return task, proof


def save_version(get, task, folder, temp):
    folder.mkdir(parents=True, exist_ok=True)
    item = next(i for i in task["items"] if i["kind"] == "video")
    base = f"/api/works/{item['work']}/v/{item['version']}"
    for fn, mode in {
        "film.mp4": "video",
        "poster.png": "offer-poster",
        "captions.srt": "subtitles",
        "post.txt": "post",
    }.items():
        (folder / fn).write_bytes(get(base + "/" + mode).content)
    zip_path = temp / (folder.name + ".zip")
    zip_path.write_bytes(get(base + "/edit-source").content)
    with ZipFile(zip_path) as z:
        timeline = json.loads(z.read("timeline.json"))
        assert z.read("captions.srt") == (folder / "captions.srt").read_bytes()
        picture = sha256(z.read("picture.mp4")).hexdigest()
        with wave.open(BytesIO(z.read("voice.wav")), "rb") as w:
            rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
            spoken = w.readframes(w.getnframes())
        music_path = z.read("music-ducked.wav")
    src = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,codec_type,width,height,r_frame_rate,nb_frames:format=duration",
                "-of",
                "json",
                str(folder / "film.mp4"),
            ]
        )
    )
    video = next(v for v in src["streams"] if v["codec_type"] == "video")
    assert (
        video["width"],
        video["height"],
        video["r_frame_rate"],
        video["nb_frames"],
    ) == (720, 1280, "24/1", "360"), src
    assert float(src["format"]["duration"]) == 15 and any(
        s["codec_name"] == "aac" for s in src["streams"]
    ), src
    boundary = timeline["shots"][-1]["startFrame"] / timeline["fps"]
    split = round(boundary * rate) * width * channels
    take = BytesIO(music_path)
    with wave.open(take) as w:
        bed = w.readframes(round(boundary * w.getframerate()))
    record = dict(
        work=item["work"],
        version=item["version"],
        inputAudioRate=rate,
        pictureSHA256=picture,
        unchangedVoiceWindowSeconds=[0, boundary],
        voicePrefixSHA256=sha256(spoken[:split]).hexdigest(),
        voiceEndingSHA256=sha256(spoken[split:]).hexdigest(),
        musicPrefixSHA256=sha256(bed).hexdigest(),
        masterSHA256=sha256((folder / "film.mp4").read_bytes()).hexdigest(),
        media=src,
        narration=[s["narration"] for s in timeline["shots"]],
        captions=timeline["captions"],
    )
    versions = get("/api/works/" + item["work"]).json()["versions"]
    v = next(x for x in versions if x["n"] == item["version"])
    record["quality"] = v.get("quality", [])
    record["factReadback"] = v.get("merchantOfferProof")
    record["merchantOffer"] = v["plan"].get("merchantOffer")
    record["shotStyles"] = [s.get("voiceStyle") for s in timeline["shots"]]
    record["narrator"] = timeline.get("narrator")
    fact = record["factReadback"]
    expected = "18.90" if folder.name == "before" else "19.90"
    retired = "19.90" if expected == "18.90" else "18.90"
    assert fact["offer"] == {
        "product": "抹茶拿铁",
        "currency": "CNY",
        "weekday": "周五",
        "channel": "到店",
        "amount": expected,
    }
    subtitle_pixels = [
        [r["text"] for r in cue["readback"]] for cue in fact["burnedCaptions"]
    ]
    surfaces = [
        "\n".join(r["text"] for r in fact["poster"]["readback"]),
        "\n".join(line for cue in subtitle_pixels for line in cue),
        (folder / "captions.srt").read_text(),
        (folder / "post.txt").read_text(),
    ]
    assert all(
        expected in text and "周五" in text and "到店" in text and retired not in text
        for text in surfaces
    ), surfaces
    assert "周五到店价" in surfaces[0]
    # The service also accepts equivalent Mandarin currency readings, e.g. 十九元九角.
    from server.merchant_offer import require_facts

    require_facts(fact["spoken"], fact["offer"], "下载成片口播读回", audio=True)
    return record


def make_message(post, chat, **values):
    result = post(
        "/api/agent/conversations/" + chat + "/messages",
        json={"requestKey": new_key(), **values},
    )
    return result.json()["tasks"][-1]


def run_base(get, post, folder, temp, local):
    state = get("/api/state").json()
    assert state["credits"] == 120 and not state["reservations"]
    with PROOF["SOURCE"].open("rb") as source:
        asset = post(
            "/api/assets", files={"image": ("抹茶拿铁.webp", source, "image/webp")}
        ).json()
    (folder / "uploaded.png").write_bytes(get(asset["original"]).content)
    local.update(
        chat=post("/api/agent/conversations", json={}).json()["id"], asset=asset["id"]
    )
    card = make_message(
        post,
        local["chat"],
        text=BRIEF,
        options={
            "kind": "video",
            "asset": asset["id"],
            "assetMode": "original",
            "assetConfirmed": True,
            "identityRegion": PROOF["REGION"],
            "promotedItem": "抹茶拿铁",
            "ownCopy": "\n".join(LINES),
        },
    )
    if card["status"] != "quoted":
        raise RuntimeError(str(card))
    task, charge = approve(get, post, card)
    record = save_version(get, task, folder / "before", temp)
    local.update(
        work=record["work"], version=record["version"], before=record, baseCharge=charge
    )


def compare_first_shots(folder, boundary):
    def frame_digests(movie):
        output = subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(movie),
                "-map",
                "0:v:0",
                "-t",
                str(boundary),
                "-f",
                "framemd5",
                "-",
            ],
            text=True,
            timeout=60,
        )
        return [
            line.rsplit(",", 1)[-1].strip()
            for line in output.splitlines()
            if not line.startswith("#")
        ]

    before = frame_digests(folder / "before/film.mp4")
    after = frame_digests(folder / "after/film.mp4")
    assert len(before) == round(24 * boundary) and before == after
    return len(before)


def run_edit(get, post, folder, temp, local):
    starting_balance = get("/api/state").json()["credits"]
    ref = {"id": local["work"], "version": local["version"]}
    card = make_message(post, local["chat"], text=EDIT, action="new", workRef=ref)
    if card["status"] != "quoted":
        raise RuntimeError(str(card))
    path = task_route(card)
    pair = post(path + "/ending-previews", json={"revision": card["revision"]}).json()
    auditions = []
    for take in pair["takes"]:
        style = take["style"]
        assert style in ("warm", "bright")
        response = get(take["url"])
        name = style + ".wav"
        with wave.open(BytesIO(response.content)) as w:
            wave_seconds = round(w.getnframes() / w.getframerate(), 3)
        (folder / name).write_bytes(response.content)
        from server.merchant_offer import require_facts

        require_facts(
            take["readback"],
            {"weekday": "周五", "amount": "19.90", "channel": "到店"},
            "片尾试听",
            audio=True,
        )
        auditions.append(
            dict(
                style=style,
                file=name,
                sha256=sha256(response.content).hexdigest(),
                readback=take["readback"],
                duration=take["seconds"],
                waveDurationSeconds=wave_seconds,
                confirmedText=take["text"],
            )
        )
    assert {t["style"] for t in auditions} == {"warm", "bright"} and len(
        {t["sha256"] for t in auditions}
    ) == 2
    approved = post(
        path + "/ending-choice", json={"revision": card["revision"], "style": "bright"}
    ).json()
    assert starting_balance == get("/api/state").json()["credits"]
    task, charge = approve(get, post, approved)
    record = save_version(get, task, folder / "after", temp)
    original = local["before"]
    assert (
        original["work"] == record["work"]
        and record["version"] == original["version"] + 1
    )
    assert original["pictureSHA256"] == record["pictureSHA256"]
    record["identicalDecodedPrefixFrames"] = compare_first_shots(
        folder, record["unchangedVoiceWindowSeconds"][1]
    )
    assert original["voicePrefixSHA256"] == record["voicePrefixSHA256"]
    assert original["musicPrefixSHA256"] == record["musicPrefixSHA256"]
    assert original["voiceEndingSHA256"] != record["voiceEndingSHA256"]
    assert original["narration"][:-1] == record["narration"][:-1]
    assert original["captions"][:-1] == record["captions"][:-1]
    selected = next(t for t in auditions if t["style"] == "bright")
    with wave.open(str(folder / selected["file"])) as w:
        selected_pcm = w.readframes(w.getnframes())
        rate, stride = w.getframerate(), w.getnchannels() * w.getsampwidth()
    with ZipFile(temp / "after.zip") as z:
        with wave.open(BytesIO(z.read("voice.wav"))) as w:
            final_stem = w.readframes(w.getnframes())
    start = round(rate * record["unchangedVoiceWindowSeconds"][1]) * stride
    assert final_stem[start : start + len(selected_pcm)] == selected_pcm
    assert not any(final_stem[start + len(selected_pcm) :])
    record["selectedAuditionIsExactEndingPCM"] = True
    assert len(charge["debits"]) == 1
    local.update(
        after=record, revisionCharge=charge, auditions=auditions, previewCharged=0
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--out", type=Path, default=DEST)
    cli.add_argument(
        "--sandbox", type=Path, help="复用本机隔离验收目录；请勿指向商家项目数据"
    )
    cli.add_argument("--phase", choices=("all", "before", "after"), default="all")
    args = cli.parse_args()
    sandbox = (
        args.sandbox.resolve()
        if args.sandbox
        else Path(tempfile.mkdtemp(prefix="trupic-offer-proof-"))
    )
    sandbox.mkdir(parents=True, exist_ok=True)
    if (sandbox / "studio.sqlite3").exists() or sandbox == ROOT / ".trupic":
        raise ValueError("请选择专用于验收的新目录")
    folder = sandbox / "evidence"
    folder.mkdir(exist_ok=True)
    state = sandbox / "private.json"
    saved = read_json(state) if state.is_file() else {}
    if not saved and args.phase == "after":
        raise RuntimeError("请先跑 before 阶段")
    os.environ["TRUPIC_FILM_VOICE_ENGINE"] = "qwen3-mlx"
    os.environ["TRUPIC_QWEN_VOICE_STYLE"] = "warm"
    with PROOF["local_app"](sandbox / "db", True) as (base, _):
        session = requests.Session()
        session.trust_env = False
        if "cookie" in saved:
            session.cookies.set("trupic_workspace", saved["cookie"])
        get = partial(PROOF["request"], session, base, "GET")
        post = partial(PROOF["request"], session, base, "POST")
        if args.phase != "after":
            if saved:
                raise ValueError("before 阶段须使用空验收目录")
            run_base(get, post, folder, sandbox, saved)
            saved["cookie"] = session.cookies["trupic_workspace"]
            state.touch(mode=0o600, exist_ok=False)
            write_json(state, saved)
        if args.phase != "before":
            run_edit(get, post, folder, sandbox, saved)
            write_json(state, saved)
            write_json(
                folder / "checks.json",
                {
                    k: saved[k]
                    for k in (
                        "before",
                        "after",
                        "baseCharge",
                        "revisionCharge",
                        "auditions",
                        "previewCharged",
                    )
                },
            )
            shutil.copytree(folder, args.out, dirs_exist_ok=True)
            print("成片与核对记录已交付", args.out)


if __name__ == "__main__":
    main()
