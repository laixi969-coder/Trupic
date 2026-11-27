"""Package an already settled background comparison. This proof never calls a generation API."""

import argparse
import json
import os
import runpy
import shutil
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEMO = ROOT / "docs/research/video-integration"
BLIND = runpy.run_path(str(ROOT / "scripts/proof-merchant-blind.py"))


def read(path):
    return json.loads(path.read_text())


def digest(content):
    return sha256(content).hexdigest()


def delta(start, end):
    return round(
        (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 3
    )


def check_movie(path):
    streams = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", path]
        )
    )["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    assert (
        video["width"],
        video["height"],
        video["r_frame_rate"],
        video["nb_frames"],
        float(video["duration"]),
    ) == (720, 1280, "24/1", "360", 15)
    # Hash the delivered AAC packets, including the whole soundtrack.
    audio = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            path,
            "-map",
            "0:a:0",
            "-c:a",
            "copy",
            "-f",
            "adts",
            "-",
        ]
    )
    return digest(audio)


def compare_pixels(before, after):
    def read_frames(path):
        return subprocess.Popen(
            [
                "ffmpeg",
                "-v",
                "error",
                "-threads",
                "1",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-threads",
                "1",
                "-vf",
                "scale=180:320",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
        )

    corner, cup = [], []
    with read_frames(before) as a, read_frames(after) as b:
        for _ in range(360):

            def frame(proc):
                return (
                    np.frombuffer(proc.stdout.read(320 * 180 * 3), dtype=np.uint8)
                    .reshape((320, 180, 3))
                    .astype(float)
                )

            diff = np.abs(frame(a) - frame(b))
            corner.append(float(diff[:28, :48].mean()))
            cup.append(float(diff[164:198, 85:111].mean()))
        assert not a.stdout.read(1) and not b.stdout.read(1)
        assert not a.wait() and not b.wait()
    assert max(cup) < 5 and min(corner) > 5, (max(cup), min(corner))
    return {
        "framesCompared": 360,
        "analysisSize": [180, 320],
        "cupCenter": [85, 164, 111, 198],
        "upperLeft": [0, 0, 48, 28],
        "maxCupMeanAbsoluteDelta": round(max(cup), 3),
        "minBackgroundMeanAbsoluteDelta": round(min(corner), 3),
    }


def build(private, seed, output, chrome):
    saved = BLIND["baseline"](seed)
    os.environ["TRUPIC_DATA"] = str(private / "db")
    from server import app as studio
    from server.merchant_blind import version_info

    settled, clock = read(private / "settled.json"), read(private / "clock.json")
    prediction = read(private / "prediction.json")["data"]
    before = read(private / "bill-before.json")["balance"]["cash"]
    after = read(private / "bill-after.json")["balance"]["cash"]
    charge = Decimal(str(prediction["price"]))
    assert (
        prediction["status"] == "completed" and prediction["charge_status"] == "charged"
    )
    assert before["currency"] == after["currency"] == "usd"
    assert Decimal(before["value"]) - Decimal(after["value"]) == charge
    assert settled["before"] - settled["after"] == settled["quoted"] == 1
    assert [r["delta"] for r in settled["ledger"]] == [-1] and settled["threeApprovals"]

    client = studio.app.test_client()
    client.set_cookie("trupic_workspace", saved["cookie"])
    state = client.get("/api/state").json
    work, tenant = saved["work"], state["workspace"]
    folder = private / "db" / tenant / "works" / work
    local, cloud = folder / "2", folder / "3"
    assert digest((local / "video.mp4").read_bytes()) == saved["after"]["masterSHA256"]
    assert (cloud / "captions.srt").read_bytes() == (
        local / "captions.srt"
    ).read_bytes()
    assert check_movie(local / "video.mp4") == check_movie(cloud / "video.mp4")
    tracks = {}
    with ZipFile(local / "edit.zip") as a, ZipFile(cloud / "edit.zip") as b:
        for name in a.namelist():
            if (
                name.endswith((".wav", ".srt", ".edl", ".png"))
                or name == "timeline.json"
            ):
                assert a.read(name) == b.read(name), name
                tracks[name] = digest(a.read(name))
    pixels = compare_pixels(local / "video.mp4", cloud / "video.mp4")

    with studio.db() as conn:
        first, second = [version_info(conn, tenant, work, i) for i in (2, 3)]
        assert (
            first["offer"] == second["offer"] and second["offer"]["amount"] == "19.90"
        )
        version = conn.execute(
            "SELECT spec FROM version WHERE work=? AND n=3", (work,)
        ).fetchone()
        plan = json.loads(version["spec"])["plan"]
        assert (
            plan["videoProviderReceipt"]["predictionId"] == prediction["id"]
            and plan["videoModel"] == prediction["model"]
        )
        asset = conn.execute(
            "SELECT count(distinct json_extract(spec,'$.asset')) FROM version WHERE work=? AND n IN (2,3)",
            (work,),
        ).fetchone()[0]
        assert asset == 1
    query = client.post(
        "/api/agent/blind-reviews",
        json={
            "source": "demo",
            "briefId": "food-01",
            "work": work,
            "baseVersion": 2,
            "revisionVersion": 3,
        },
    )
    assert query.status_code == 200, query.json
    blank = query.json
    assert blank["status"] == "open" and not blank["reveal"]
    output.mkdir(exist_ok=True, parents=True)
    movies = {2: local / "video.mp4", 3: cloud / "video.mp4"}
    media, versions = {}, {}
    actual_charge = {"amount": str(charge), "currency": "USD", "field": "price"}
    second["modelCharge"] = actual_charge
    for row in blank["options"]:
        url, slot = row["url"], row["slot"]
        assert client.get(url, headers={"Range": "bytes=0-31"}).status_code == 206
        assert studio.app.test_client().get(url).status_code == 404
        data = client.get(url).data
        n = next(i for i, p in movies.items() if digest(p.read_bytes()) == digest(data))
        media[slot] = str(movies[n])
        versions[slot] = first if n == 2 else second
    assert len(set(media.values())) == 2
    for version in versions.values():
        version.pop("facts", None)
    trial = BLIND["call_browser"](
        "offline",
        {
            "blank": blank,
            "reveal": {
                "factChanges": [],
                "firstDraftEvidence": "no_first_draft",
                "versions": versions,
            },
            "media": media,
            "output": str(output / "自己盲选.html"),
            "chrome": chrome,
        },
    )
    shutil.copyfile(cloud / "video.mp4", output / "h3.mp4")
    report = {
        "model": prediction["model"],
        "chargeStatus": prediction["charge_status"],
        "modelCharge": actual_charge,
        "accountCashDeltaUSD": str(-charge),
        "providerPredictionFingerprint": digest(prediction["id"].encode())[:16],
        "providerCreatedUtc": prediction["created_at"],
        "providerCompletedUtc": prediction["completed_at"],
        "providerSeconds": prediction["latency_ms"] / 1000,
        "backgroundReadySeconds": delta(clock["startUtc"], clock["backgroundReadyUtc"]),
        "firstSubmissionToFinalDeliverySeconds": delta(
            clock["startUtc"], second["deliveredAt"]
        ),
        "local": first,
        "h3": second,
        "startingCredits": settled["before"],
        "endingCredits": settled["after"],
        "negativeEntries": len(settled["ledger"]),
        "approvalsForSameJob": 3,
        "sharedTrackHashes": tracks,
        "encodedAudioSHA256": check_movie(cloud / "video.mp4"),
        "localFilmSHA256": digest(movies[2].read_bytes()),
        "h3FilmSHA256": digest(movies[3].read_bytes()),
        "visualComparison": pixels,
        "offlinePlayback": trial,
    }
    (output / "checks.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    print(
        "交付回执",
        report["providerSeconds"],
        second["productionSeconds"],
        report["firstSubmissionToFinalDeliverySeconds"],
        charge,
        pixels,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "private", type=Path, help="已结算的 H3 验收目录（含数据库及供应商原始账单）"
    )
    parser.add_argument("--seed", type=Path)
    parser.add_argument("--output", type=Path, default=DEMO / "matcha-h3-blind")
    parser.add_argument(
        "--chrome",
        default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    args = parser.parse_args()
    build(
        args.private.resolve(),
        args.seed or BLIND["find_seed"](),
        args.output,
        args.chrome,
    )
