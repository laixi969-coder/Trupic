"""Run a real merchant chat, approve its quote twice and verify the delivered MP4.

Run .venv/bin/python scripts/proof-product-film.py --help for local fixture options.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from functools import partial
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from zipfile import ZipFile

import numpy as np
import requests
from PIL import Image
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "server/scenes/matcha.webp"
DEST = ROOT / "docs/research/video-integration/merchant-demo"
REGION = [0.32, 0.31, 0.70, 0.65]
BRIEF = "用这张抹茶拿铁的商品原图做一条15秒竖屏短片，保留商品原样，想让顾客到店点一杯。"
ONE_LINE = "给店里的抹茶拿铁做一条15秒竖屏口播短片，介绍杯壁上抹茶和牛奶的分层，邀请顾客到店点一杯。"
LINES = ["这一杯，先别搅。", "顺着杯壁看，抹茶和牛奶留下了两种颜色。", "想喝抹茶拿铁？到店点一杯。"]


@contextmanager
def local_app(db_path, local_model):
    # Every run starts with an empty tenant store and zero external model or storage connections.
    for key in list(os.environ):
        if key.startswith("TRUPIC_") and not key.startswith(("TRUPIC_FILM_VOICE_", "TRUPIC_QWEN_VOICE_")):
            os.environ.pop(key)
    os.environ.update(TRUPIC_DATA=str(db_path), TRUPIC_VIDEO_RENDERER="ffmpeg")
    if local_model:
        os.environ.update(TRUPIC_MODEL="Qwen3-VL-2B-Instruct",
                          TRUPIC_MODEL_URL="http://127.0.0.1:7395/v1/chat/completions",
                          TRUPIC_VISION_MODEL="Qwen3-VL-2B-Instruct",
                          TRUPIC_VISION_URL="http://127.0.0.1:7395/v1/chat/completions")
    from server import app as studio

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    with make_server("127.0.0.1", 0, studio.app, threaded=True) as http:
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{http.server_port}", studio
        finally:
            http.shutdown()
            thread.join()


def request(session, base, method, path, **kwargs):
    response = session.request(method, base + path, timeout=180, **kwargs)
    if not response.ok:
        details = response.json().get("error") if response.headers.get("Content-Type", "").startswith("application/json") else response.text[:800]
        raise RuntimeError(f"{method} {path}: {response.status_code} {details}")
    return response


def browser_evidence(base, session, workspace, chat, output, chrome):
    if not chrome:
        return
    config = dict(base=base, workspace=workspace, chat=chat, output=str(output),
                  chrome=chrome, cookie=session.cookies["trupic_workspace"])
    run = subprocess.run(["node", str(ROOT / "scripts/proof-product-film-screenshot.cjs")],
                         input=json.dumps(config), text=True, stdout=subprocess.PIPE, check=True, timeout=65)
    return json.loads(run.stdout) if run.stdout else None


def audio_samples(path):
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"]
    return np.frombuffer(subprocess.check_output(command, timeout=30), dtype="<f4")


def verify_audio(output):
    spoken = audio_samples(output / "voice.wav")
    movie = audio_samples(output / "film.mp4")
    amount = min(len(spoken), len(movie))
    # FFmpeg AAC can add priming samples. Match within 20 ms.
    result = []
    for shift in range(-160, 161):
        start = max(0, -shift)
        end = min(amount, amount - shift)
        result.append(float(np.corrcoef(spoken[start:end], movie[start + shift:end + shift])[0, 1]))
    best = max(result)
    if not np.isfinite(best) or best < 0.70:
        raise RuntimeError(f"最终 AAC 与独立旁白的相关性异常 ({best:.3f})")
    return round(best, 4)


def frame_strip(output, cues):
    shots = sorted({cue["shotIndex"] for cue in cues})
    frame_numbers = []
    for index in shots:
        cue = next(cue for cue in cues if cue["shotIndex"] == index)
        frame_numbers.append((cue["startFrame"] + cue["endFrame"] - 1) // 2)
    selected = "+".join(f"eq(n,{frame})" for frame in frame_numbers)
    filters = f"select='{selected}',scale=270:480,tile={len(shots)}x1"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(output / "film.mp4"),
                    "-vf", filters, "-frames:v", "1", "-q:v", "2", str(output / "frames.jpg")],
                   timeout=30, check=True)


def save_media(get, task, output, marked):
    item = next(item for item in task["items"] if item["kind"] == "video")
    work = get("/api/works/" + item["work"]).json()
    version = work["versions"][0]
    assert version["plan"]["productNarration"]
    for filename, url in {"film.mp4": item["download"], "edit.zip": version["editSource"]}.items():
        (output / filename).write_bytes(get(url).content)
    published = next(item for item in task["items"] if item["kind"] == "copy")
    (output / "post.txt").write_bytes(get(published["download"]).content)
    with ZipFile(output / "edit.zip") as archive:
        members = archive.namelist()
        middle = version["storyboard"][1]
        if middle.get("evidence", {}).get("source") == "完整原图" and not middle.get("caption"):
            with archive.open("title-2.png") as part, Image.open(part) as layer:
                assert layer.getchannel("A").getbbox() is None, "第二镜显示了内部证据标签"
        for name in ("voice.wav", "captions.srt", "timeline.json"):
            (output / name).write_bytes(archive.read(name))
    media = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,avg_frame_rate,nb_frames:format=duration",
         "-of", "json", str(output / "film.mp4")], timeout=20))
    video = next(s for s in media["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"], video["avg_frame_rate"], int(video["nb_frames"])) == (720, 1280, "24/1", 360)
    assert abs(float(media["format"]["duration"]) - 15) < 0.1
    assert any(s["codec_name"] == "aac" for s in media["streams"])
    if os.getenv("TRUPIC_FILM_VOICE_ENGINE") == "qwen3-mlx":
        assert "qwen" in version["narration"]["provider"].lower(), version["narration"]
    board = version["storyboard"]
    if marked:
        assert any("已单独比对商家框选" in c["detail"] for c in version["quality"])
        assert board[1]["evidence"]["region"] == REGION
    assert get(version["subtitles"]).content == (output / "captions.srt").read_bytes()
    timeline = json.loads((output / "timeline.json").read_text())
    assert [shot["narration"] for shot in timeline["shots"]] == [shot["narration"] for shot in board]
    cues = timeline["captions"]
    frame_strip(output, cues)
    for index, shot in enumerate(board):
        scoped = [cue for cue in cues if cue["shotIndex"] == index]
        assert "".join(cue["text"] for cue in scoped) == shot["narration"]
        assert all(shot["start"] <= cue["start"] < cue["end"] <= shot["end"] for cue in scoped)
    return dict(media=media, storyboard=board, editFiles=members, narration=version["narration"],
                aacToVoiceCorrelation=verify_audio(output), quality=version["quality"])


def prove(base, studio, output, chrome, generated):
    session = requests.Session()
    session.trust_env = False
    get = partial(request, session, base, "GET")
    post = partial(request, session, base, "POST")
    initial = get("/api/state").json()
    with SOURCE.open("rb") as handle:
        asset = post("/api/assets", files={"image": ("抹茶拿铁.webp", handle, "image/webp")}).json()
    assert not asset["risk"]
    (output / "original.png").write_bytes(get(asset["original"]).content)
    chat = post("/api/agent/conversations", json={}).json()["id"]
    options = dict(asset=asset["id"], assetMode="original", assetConfirmed=True, identityRegion=REGION,
                   visualDetail=dict(region=REGION, label="杯壁上的抹茶纹路"))
    if generated:
        options = {"asset":asset["id"]}
    else:
        options["ownCopy"] = "\n".join(LINES)
    brief = ONE_LINE if generated else BRIEF
    expressive_order = generated and os.getenv("TRUPIC_FILM_VOICE_ENGINE") == "qwen3-mlx"
    if generated:
        brief += "配音语气轻快一点，像店员把杯子递给一位顾客那样说。"
    message = dict(text=brief, options=options, requestKey=uuid.uuid4().hex)
    chat_url = "/api/agent/conversations/" + chat
    reply = post(chat_url + "/messages", json=message).json()
    card = reply["tasks"][-1]
    task_url = "/api/agent/tasks/" + card["id"]
    if generated:
        assert card["status"] == "waiting_script", card
        card = post(task_url + "/options", json={"revision":card["revision"]}).json()
    assert card["status"] == "quoted", card
    words = [s["narration"] for s in card["storyboard"]]
    if not generated:
        assert words == LINES, words
    quoted = get("/api/state").json()
    assert quoted["credits"] == initial["credits"] and not quoted["reservations"]
    browser = browser_evidence(base, session, initial["workspace"], chat, output / "quote.png", chrome)
    if browser:
        approval, accepted = browser["approval"], browser["accepted"]
    else:
        approval = dict(quoteId=card["quoteId"], confirmedCost=card["cost"], revision=card["revision"],
                        approvalType="production", requestKey=uuid.uuid4().hex)
        accepted = post(task_url + "/approve", json=approval).json()
    repeated = post(task_url + "/approve", json=approval).json()
    jobs = [x["job"] for x in accepted["items"]]
    assert jobs and jobs == [x["job"] for x in repeated["items"]]
    timeout = time.monotonic() + 240
    while True:
        evidence = get(task_url + "/events").json()
        final = evidence["task"]
        if final["status"] == "delivered":
            break
        if final["status"] in ("failed", "cancelled") or time.monotonic() >= timeout:
            raise RuntimeError(f"短片制作未完成：{final['items']}")
        time.sleep(.25)
    after = get("/api/state").json()
    assert initial["credits"] - after["credits"] == card["cost"]
    totals = Counter()
    for operation in after["reservations"]:
        totals[operation["action"]] += operation["amount"]
    assert totals == {"reserve":card["cost"], "consume":card["cost"]}, totals
    assert sum(row["delta"] for row in after["ledger"] if row["delta"] < 0) == -card["cost"]
    assert sum(e["type"] == "reserved" for e in evidence["events"]) == 1
    browser_evidence(base, session, initial["workspace"], chat, output / "delivery.png", chrome)
    verified = save_media(get, final, output, marked=not generated)
    if expressive_order:
        assert verified["narration"]["style"] == "bright" and verified["narration"]["styleApplied"]
    if (ROOT / ".trupic/models/ggml-small.bin").is_file() and (ROOT / ".trupic/bin/whisper-cli").is_file():
        audio = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(output / "film.mp4"),
                                         "-vn", "-map", "0:a:0", "-f", "mp3", "-"], timeout=20)
        transcribed = post("/api/agent/voice/transcribe", files={"audio": ("delivered.mp3", audio, "audio/mpeg")})
        verified["independentTranscript"] = transcribed.json()["text"]
    assert words == [s["narration"] for s in verified["storyboard"]]
    with studio.db() as db:
        calls = [dict(row) for row in db.execute("SELECT kind,model,COUNT(*) calls,SUM(ok) ok FROM model_call GROUP BY kind,model")]
    if generated:
        assert any(row["kind"] == "text" and row["ok"] and row["model"] == "Qwen3-VL-2B-Instruct" for row in calls)
    report = dict(inputMode="本机模型出稿" if generated else "商家三行定稿", brief=brief, source="server/scenes/matcha.webp",
                  region=None if generated else REGION, uploaded={key: asset[key] for key in ("name", "width", "height", "action", "risk")},
                  confirmedScript=words, deliveries=card["deliveries"], status=final["status"], modelCalls=calls,
                  before=initial["credits"], afterQuote=quoted["credits"], confirmedCost=card["cost"], after=after["credits"],
                  ledger=after["ledger"], reservations=after["reservations"], replayReturnedSameJobs=True, approvalMethod="网页确认按钮" if chrome else "营销助理 API",
                  events=evidence["events"], **verified)
    (output / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k:report[k] for k in ("inputMode", "status", "before", "confirmedCost", "after", "aacToVoiceCorrelation")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", action="store_true", help="使用项目的本机 Qwen 服务生成初稿，须先运行 npm run vision:serve")
    parser.add_argument("--chrome", help="已安装的 Chrome 或 Chromium 路径，附加截取真实网页；须已运行 npm ci 和 npm run build")
    parser.add_argument("--out", type=Path, help="验收成品目录；默认位于 docs/research/video-integration/merchant-demo")
    args = parser.parse_args()
    destination = (args.out or (DEST / "generated" if args.generated else DEST)).resolve()
    with tempfile.TemporaryDirectory(prefix="trupic-film-proof-") as workspace:
        root = Path(workspace)
        proof = root / "proof"
        proof.mkdir()
        with local_app(root / "db", args.generated) as app:
            prove(*app, proof, args.chrome, args.generated)
        destination.mkdir(parents=True, exist_ok=True)
        for item in proof.iterdir():
            shutil.copyfile(item, destination / item.name)
