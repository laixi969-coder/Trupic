"""Local dictation and reply audio for the agent. These routes never submit a task."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from flask import Blueprint, Response, abort, jsonify, request

from .media import ROOT

RATE = 16_000
MAX_SECONDS = 60
MAX_AUDIO_BYTES = 6 * 1024 * 1024
MAX_TEXT = 600
LOCAL = ROOT / ".trupic"
SILENT_MESSAGE = "没有听到清楚的人声，请靠近麦克风再说一次。"
ACTIVE = set()
LOCK = threading.Lock()


@contextmanager
def voice_slot(tenant):
    with LOCK:
        if tenant in ACTIVE or len(ACTIVE) >= 2:
            abort(429, description="语音服务正在处理其他请求，请稍后再试。")
        ACTIVE.add(tenant)
    try:
        yield
    finally:
        with LOCK:
            ACTIVE.discard(tenant)


def tool(name, configured=None):
    binary = shutil.which(str(configured or name))
    if not binary:
        abort(503, description="服务器缺少本地语音工具，请先使用文字输入。")
    return binary


def run(args, message, *, timeout, stdin=None, failure_status=503):
    try:
        result = subprocess.run(
            args, input=stdin, stdin=subprocess.DEVNULL if stdin is None else None,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        abort(503, description="语音处理超时，请缩短内容后重试。")
    except OSError:
        abort(503, description="服务器暂时无法启动本地语音工具。")
    if result.returncode:
        abort(failure_status, description=message)


def decode(audio, folder):
    source, wav = folder / "upload", folder / "mono.wav"
    source.write_bytes(audio)
    # Restrict input demuxers and protocols to local recording containers.
    # Decode a little past the limit so that longer recordings are rejected whole.
    run([
        tool("ffmpeg"), "-nostdin", "-v", "error", "-protocol_whitelist", "file",
        "-format_whitelist", "wav,mp3,aac,mov,matroska,webm,ogg,flac",
        "-threads", "1", "-i", source, "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-t", str(MAX_SECONDS + 1), "-ar", str(RATE), "-ac", "1",
        "-map_metadata", "-1", "-c:a", "pcm_s16le", wav,
    ], "录音无法解码，请重新录制后发送。", timeout=18, failure_status=422)
    with wave.open(str(wav), "rb") as stream:
        length = stream.getnframes()
        # MP3 and AAC encoders can append part of a final codec frame.
        if length > MAX_SECONDS * RATE + RATE // 10:
            abort(422, description=f"单段录音最多 {MAX_SECONDS} 秒，请分段发送。")
        pcm = stream.readframes(min(length, MAX_SECONDS * RATE))
    if length > MAX_SECONDS * RATE:
        with wave.open(str(wav), "wb") as clipped:
            clipped.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            clipped.writeframes(pcm)
    samples = np.frombuffer(pcm, dtype="<i2")
    # Six active 20 ms windows suppress silence, DC offset and isolated clicks.
    window = RATE // 50
    frames = samples[:samples.size // window * window].reshape(-1, window)
    if not frames.size or np.count_nonzero(frames.std(axis=1) > 65) < 6:
        abort(422, description=SILENT_MESSAGE)
    return wav


def transcribe(audio, folder):
    wav = decode(audio, folder)
    local_cli = LOCAL / "bin" / "whisper-cli"
    configured_cli = os.getenv("TRUPIC_WHISPER_CLI") or (local_cli if local_cli.is_file() else None)
    cli = tool("whisper-cli", configured_cli)
    model = Path(os.getenv("TRUPIC_WHISPER_MODEL") or LOCAL / "models" / "ggml-small.bin").expanduser()
    if not model.is_file():
        abort(503, description="服务器尚未配置中文语音识别模型，请先使用文字输入。")
    output = folder / "result"
    run([
        cli, "-m", model, "-f", wav, "-l", "zh", "-nt", "-np", "-sns", "-nf",
        "--prompt", "以下是简体中文普通话的语音转写。", "-otxt", "-of", output,
    ], "本地语音识别暂时不可用，请先使用文字输入。", timeout=90)
    result = output.with_suffix(".txt")
    if not result.is_file():
        abort(503, description="本地语音模型未能完成识别，请先使用文字输入。")
    text = "".join(line.strip() for line in result.read_text(encoding="utf-8").splitlines())
    text = re.sub(r"\[[^\]]*\]|[（(](?:音乐|静音|无声|杂音|掌声)[）)]", "", text).strip()
    if not any(c.isalnum() for c in text):
        abort(422, description=SILENT_MESSAGE)
    return text


def speak(text, folder):
    if sys.platform == "darwin":
        source = folder / "reply.aiff"
        voice = os.getenv("TRUPIC_TTS_VOICE") or "Tingting"
        command = [tool("say"), "-v", voice, "-o", source, "-f", "-"]
        # macOS interprets double brackets as synthesizer commands, even in stdin.
        text = text.replace("[", " ").replace("]", " ")
    else:
        source = folder / "reply.wav"
        voice = os.getenv("TRUPIC_TTS_VOICE") or "cmn"
        command = [tool("espeak-ng"), "-v", voice, "-w", source, "--stdin"]
    run(command, "中文朗读暂时不可用，请查看文字回复。", timeout=25, stdin=text.encode("utf-8"))
    mp3 = folder / "reply.mp3"
    run([
        tool("ffmpeg"), "-nostdin", "-v", "error", "-i", source, "-map", "0:a:0",
        "-map_metadata", "-1", "-ac", "1", "-ar", "24000", "-c:a", "libmp3lame",
        "-b:a", "64k", mp3,
    ], "语音回复转换失败，请查看文字回复。", timeout=25)
    return mp3.read_bytes()


def register(app, reqtenant):
    routes = Blueprint("agent_voice", __name__, url_prefix="/api/agent/voice")

    @routes.errorhandler(413)
    def too_large(_):
        error = "录音文件最多 6 MB。" if request.endpoint.endswith("transcription") else "朗读文本太长，请缩短后重试。"
        return jsonify(error=error), 413

    @routes.post("/transcribe")
    def transcription():
        request.max_content_length = min(request.max_content_length, MAX_AUDIO_BYTES + 64 * 1024)
        with voice_slot(reqtenant()):
            upload = request.files.get("audio")
            if upload is None:
                abort(400, description="请上传一段录音。")
            audio = upload.stream.read(MAX_AUDIO_BYTES + 1)
            if not audio:
                abort(400, description="录音是空的，请重新录制。")
            if len(audio) > MAX_AUDIO_BYTES:
                abort(413)
            with tempfile.TemporaryDirectory(prefix="trupic-listen-") as tmp:
                return jsonify(text=transcribe(audio, Path(tmp)))

    @routes.post("/speak")
    def speech():
        request.max_content_length = min(request.max_content_length, 16 * 1024)
        value = request.get_json(silent=True)
        text = value.get("text") if isinstance(value, dict) else None
        if not isinstance(text, str) or not text.strip() or re.search(r"[\x00\ud800-\udfff]", text):
            abort(400, description="请输入需要朗读的文字。")
        text = text.strip()
        if len(text) > MAX_TEXT:
            abort(400, description=f"每次最多朗读 {MAX_TEXT} 个字，请分段播放。")
        with voice_slot(reqtenant()), tempfile.TemporaryDirectory(prefix="trupic-speak-") as tmp:
            return Response(speak(text, Path(tmp)), mimetype="audio/mpeg")

    app.register_blueprint(routes)
