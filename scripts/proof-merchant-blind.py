"""Record an isolated merchant blind ballot for two previously delivered matcha films."""
import argparse
import hashlib
import json
import runpy
import shutil
import sqlite3
import statistics
import subprocess
import tempfile
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
OFFER = ROOT / "docs/research/video-integration/matcha-friday-revision"
OUT = ROOT / "docs/research/video-integration/matcha-blind-review"
HELPERS = runpy.run_path(str(ROOT / "scripts/proof-product-film.py"))


def baseline(path):
    saved = json.loads((path / "private.json").read_text())
    expected = json.loads((OFFER / "checks.json").read_text())
    for which in ("before", "after"):
        if any(saved[which][key] != expected[which][key] for key in ("work", "version", "masterSHA256")):
            raise ValueError("请选择交付抹茶两版成片时使用的隔离验收目录")
    if not (path / "db/studio.sqlite3").is_file():
        raise ValueError("未找到原验收账本")
    return saved


def find_seed():
    for prefix in (Path(tempfile.gettempdir()), Path("/tmp")):
        for pattern in ("trupic-offer-proof-*", "trupic-price-*"):
            for path in prefix.glob(pattern):
                try:
                    baseline(path)
                except (OSError, KeyError, ValueError):
                    continue
                return path
    raise ValueError("请用 --seed 指定 proof-offer-ending.py 为这两版成片保存的隔离验收目录")


def cloned_seed(source, target):
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("studio.sqlite3*"))
    with sqlite3.connect(f"file:{source / 'studio.sqlite3'}?mode=ro", uri=True) as old:
        if old.execute("SELECT COUNT(*) FROM merchant").fetchone()[0] != 1:
            raise ValueError("仅可复制单个演示商家的专用验收目录")
        with sqlite3.connect(target / "studio.sqlite3") as new:
            old.backup(new)


def call_browser(mode, config):
    res = subprocess.run(["node", str(ROOT / "scripts/proof-merchant-blind-browser.cjs"), mode],
                         cwd=ROOT, input=json.dumps(config, ensure_ascii=False), capture_output=True,
                         text=True, timeout=210)
    if res.returncode:
        raise RuntimeError(res.stderr[-2400:])
    return json.loads(res.stdout)


def video_recording(temp, samples, times, output):
    frames = times["frames"]
    positions = {s: [] for s in ("A", "B")}
    lines = []
    first = frames[0]["time"]
    for index, frame in enumerate(frames):
        interval = frames[index + 1]["time"] - frame["time"] if index + 1 < len(frames) else 0.12
        lines.extend([f"file '{frame['file']}'", f"duration {max(.01, interval):.4f}"])
        for slot, playhead in frame["play"].items():
            if 0.1 < playhead < 14.9:
                positions[slot].append(frame["time"] - first - playhead)
    lines.append(f"file '{frames[-1]['file']}'")
    (temp / "frames/movie.txt").write_text("\n".join(lines) + "\n")
    offsets = [round(statistics.median(positions[k]) * 1000) for k in ("A", "B")]
    command = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
               "-i", str(temp / "frames/movie.txt"), "-i", str(samples["A"]), "-i", str(samples["B"]),
               "-filter_complex", f"[1:a]adelay={offsets[0]}:all=1[a];[2:a]adelay={offsets[1]}:all=1[b];[a][b]amix=inputs=2:normalize=0,apad[s]",
               "-map", "0:v", "-map", "[s]", "-vf", "fps=15", "-c:v", "libx264", "-crf", "20",
               "-threads", "2", "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
               "-shortest", "-movflags", "+faststart", str(output)]
    subprocess.run(command, check=True, timeout=140)
    return {"sampleAPlaybackStartSeconds":offsets[0] / 1000, "sampleBPlaybackStartSeconds":offsets[1] / 1000,
            "screenRecordingSeconds":round(frames[-1]["time"] - first + .12, 2)}


def run(seed, output, chrome):
    saved = baseline(seed)
    with tempfile.TemporaryDirectory(prefix="trupic-blind-proof-") as tmp:
        temp = Path(tmp)
        (temp / "frames").mkdir()
        cloned_seed(seed / "db", temp / "db")
        output.mkdir(parents=True, exist_ok=True)
        with HELPERS["local_app"](temp / "db", False) as (base, _):
            from server.voice import transcribe
            session = requests.Session()
            session.trust_env = False
            session.cookies.set("trupic_workspace", saved["cookie"])
            def req(method, path, **kwargs):
                return HELPERS["request"](session, base, method, path, **kwargs)
            state_before = req("GET", "/api/state").json()
            before_summary = req("GET", "/api/agent/blind-reviews").json()
            case = req("POST", "/api/agent/blind-reviews", json={"work":saved["work"], "revisionVersion":2,
                        "briefId":"food-01", "source":"demo"}).json()
            path = "/api/agent/blind-reviews/" + case["id"]
            blank = req("GET", path).json()
            assert blank["status"] == "open" and not blank.get("reveal")
            serialized = json.dumps(blank)
            for forbidden in (saved["work"], "revisionVersion", "role", "credits", "/api/works/", "merchantEditMinutes"):
                assert forbidden not in serialized, forbidden
            samples, transcripts = {}, {}
            for row in blank["options"]:
                slot = row["slot"]
                result = req("GET", row["url"])
                assert "mp4" in result.headers["Content-Type"] and not any(
                    tag in result.headers.get("Content-Disposition", "") for tag in (saved["work"], "before", "after", "video.mp4"))
                samples[slot] = temp / (slot + ".mp4")
                samples[slot].write_bytes(result.content)
                sample_dir = temp / ("speech-" + slot)
                sample_dir.mkdir()
                audio = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(samples[slot]), "-vn",
                            "-ac", "1", "-ar", "16000", "-f", "wav", "-"], timeout=30)
                transcripts[slot] = transcribe(audio, sample_dir)
                partial = req("GET", row["url"], headers={"Range":"bytes=0-31"})
                assert partial.status_code == 206 and len(partial.content) == 32
                foreign = requests.Session()
                foreign.trust_env = False
                unauthorized = foreign.get(base + row["url"], timeout=10)
                assert unauthorized.status_code in (401,403,404)
            # Use only the words audible in each anonymous sample for the demonstration ballot.
            wanted = [s for s, text in transcripts.items() if "十九" in text.replace(" ", "") or "19" in text]
            assert len(wanted) == 1, transcripts
            prefer = wanted[0]
            browser = call_browser("record", {"base":base, "caseId":case["id"], "cookie":saved["cookie"],
                    "chrome":chrome, "temp":str(temp), "prefer":prefer, "reason":"本次周五到店价是19.90元，片尾仍报18.90元，需要改价。"})
            submitted = req("GET", path).json()
            reveal = submitted["reveal"]
            assert reveal["firstDraftPublish"] is False and reveal["preference"] == prefer
            assert reveal["revisionSlot"] == prefer and reveal["merchantEditMinutes"] is None
            assert reveal["versions"][prefer]["credits"] == 1 and reveal["versions"][reveal["firstDraftSlot"]]["credits"] == 12
            assert req("GET", "/api/state").json()["credits"] == state_before["credits"]
            after_summary = req("GET", "/api/agent/blind-reviews").json()
            evidence = dict(origin="本机隔离账户的实际上传、制作、修改及积分账本", source="demo", briefId=blank["briefId"],
                            playbackReadback=transcripts, requestEvidence=browser["requests"],
                            reviewerSawNeutralPayload=True, foreignTenantMediaBlocked=True, rangedVideoPlayback=True,
                            openingBalance=state_before["credits"], closingBalance=state_before["credits"],
                            reveal=reveal, summaryBefore=before_summary.get("summary"), summaryAfter=after_summary.get("summary"))
            assert evidence["summaryBefore"] == evidence["summaryAfter"]
            ui_config = {"blank":blank, "reveal":reveal, "media":{k:str(v) for k,v in samples.items()},
                         "output":str(output / "自己盲选.html"), "chrome":chrome}
            call_browser("offline", ui_config)
            evidence["recording"] = video_recording(temp, samples, browser, output / "walkthrough.mp4")
            for key in ("A", "B"):
                role = "before" if reveal["firstDraftSlot"] == key else "after"
                assert hashlib.sha256(samples[key].read_bytes()).hexdigest() == saved[role]["masterSHA256"]
            (output / "checks.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False)+"\n")
            return evidence


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seed", type=Path, help="proof-offer-ending.py 创建的单商家隔离验收目录")
    cli.add_argument("--out", type=Path, default=OUT)
    cli.add_argument("--chrome", default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    args = cli.parse_args()
    e = run(args.seed or find_seed(), args.out, args.chrome)
    print(json.dumps({"recording":e["recording"], "source":e["source"], "charged":0},ensure_ascii=False))
