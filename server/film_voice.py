"""Local Mandarin commercial narration with Kokoro or expressive Qwen CustomVoice."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import venv
import wave

import numpy as np


MODEL_NAME = "kokoro-multi-lang-v1_1"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{MODEL_NAME}.tar.bz2"
MODEL_SHA256 = "b78e1ac42b852e839cceaafbe88f66806bf5860992d1d7b9a3f2ad1198427aed"
TEXT_RULES = ("phone-zh.fst", "date-zh.fst", "number-zh.fst")
RATE = 24_000
PROVIDER = "kokoro-zh-local"
QWEN_ROOT = Path(__file__).resolve().parents[1] / ".trupic" / "expressive-tts"
QWEN_REVISION = "f35faf19b0cc2160865af64ecf0f22f83d335135"
QWEN_REPO = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit"
QWEN_WEIGHTS = {"model.safetensors": 1625226859, "speech_tokenizer/model.safetensors": 682293092}
# Speech directions are separate from the approved text; they never enter the subtitles.
DIRECTIONS = {
    "warm": "用自然普通话，像店主在身边对一个人说话，轻柔亲切，稍带笑意。标点处短暂换气，语速适中。只念给定台词。",
    "bright": "用自然普通话，像店主看到熟客时，高兴地分享一个发现。声音明亮，带点惊喜，语速轻快，关键词有弹性。只念给定台词。",
}
SENTENCE = re.compile(r"[^。！？!?\n]+[。！？!?]*[”」』]?", re.UNICODE)
PREPARE = "请安装 requirements.txt 后运行 python -m server.film_voice --prepare"


def model_directory():
    default = Path(__file__).resolve().parents[1] / ".trupic" / "models" / MODEL_NAME
    return Path(os.environ.get("TRUPIC_FILM_VOICE_MODEL") or default).expanduser().resolve()


def _model_ready(folder):
    names = ("model.onnx", "voices.bin", "tokens.txt", "lexicon-us-en.txt", "lexicon-zh.txt", *TEXT_RULES)
    return all((folder / name).is_file() and (folder / name).stat().st_size > 0 for name in names)


def prepare_model():
    """Download verified public weights only when explicitly requested by the operator."""
    dest = model_directory()
    if _model_ready(dest):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as temp:
        temp = Path(temp)
        archive = temp / "kokoro.tar.bz2"
        with urllib.request.urlopen(MODEL_URL, timeout=90) as src, archive.open("wb") as out:
            shutil.copyfileobj(src, out)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != MODEL_SHA256:
                raise RuntimeError("Kokoro 语音模型下载校验失败")
        with tarfile.open(archive) as package:
            package.extractall(temp, filter="data")
        if not _model_ready(temp / MODEL_NAME):
            raise RuntimeError("Kokoro 语音模型文件不完整")
        try:
            (temp / MODEL_NAME).rename(dest)
        except OSError:
            if not _model_ready(dest):
                raise
    return dest


def _write_wav(path, samples, rate=RATE):
    with wave.open(str(path), "wb") as out:
        out.setparams((samples.shape[1] if samples.ndim == 2 else 1, 2, rate, 0, "NONE", "NONE"))
        out.writeframes((np.clip(samples, -1, 1) * 32767).round().astype("<i2").tobytes())


def _synthesize(directory, job):
    """The native engine runs in a short-lived process with a hard wall-clock limit."""
    import sherpa_onnx as sherpa

    model = model_directory()
    kokoro = sherpa.OfflineTtsKokoroModelConfig(
        model=str(model / "model.onnx"), voices=str(model / "voices.bin"),
        tokens=str(model / "tokens.txt"),
        lexicon=f"{model / 'lexicon-us-en.txt'},{model / 'lexicon-zh.txt'}",
    )
    rules = [str(model / name) for name in TEXT_RULES]
    config = sherpa.OfflineTtsConfig(model=sherpa.OfflineTtsModelConfig(
        kokoro=kokoro, num_threads=3, provider="cpu"), rule_fsts=",".join(rules))
    if not config.validate():
        raise RuntimeError("Kokoro 模型配置无效")
    engine = sherpa.OfflineTts(config)
    for index, sentence in enumerate(job["sentences"]):
        audio = engine.generate(sentence, sid=job["speaker"], speed=1.0)
        _save_line(directory, index, audio.samples, audio.sample_rate)


def _save_line(directory, index, samples, sample_rate):
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    if sample_rate != RATE or not np.isfinite(samples).all():
        raise RuntimeError("本地模型返回了无效语音")
    active = np.flatnonzero(np.abs(samples) > 0.003)
    if len(active) < RATE * 0.015:
        raise RuntimeError("本地模型未生成可听见的台词")
    # Keep low-energy onsets, consonants and breath at the end, discard model padding.
    samples = samples[max(0, active[0] - RATE // 25):active[-1] + 1 + RATE // 16]
    _write_wav(directory / f"line-{index}.wav", samples)


def _qwen_paths():
    model = Path(os.environ.get("TRUPIC_QWEN_VOICE_MODEL") or QWEN_ROOT / "model").expanduser()
    python = Path(os.environ.get("TRUPIC_QWEN_VOICE_PYTHON") or QWEN_ROOT / "venv/bin/python").expanduser()
    return model.absolute(), python.absolute()


def _qwen_ready():
    model, python = _qwen_paths()
    if sys.platform != "darwin" or platform.machine() != "arm64" or not os.access(python, os.X_OK):
        return False
    metadata = ("config.json", "vocab.json", "tokenizer_config.json", "merges.txt", "speech_tokenizer/config.json")
    if not all((model / path).is_file() for path in metadata):
        return False
    if not all((model / path).is_file() and (model / path).stat().st_size == size
               for path, size in QWEN_WEIGHTS.items()):
        return False
    try:
        probe = subprocess.run([
            python, "-c", "import importlib.util as u, mlx.core as m; "
            "raise SystemExit(not (m.metal.is_available() and u.find_spec('mlx_audio') and u.find_spec('transformers')))"
        ], capture_output=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def prepare_qwen():
    """Create the optional Apple Silicon environment and download a pinned local model."""
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("Qwen MLX 配音需要 Apple Silicon")
    model, python = _qwen_paths()
    if not os.environ.get("TRUPIC_QWEN_VOICE_PYTHON"):
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(QWEN_ROOT / "venv")
        uv = shutil.which("uv")
        install = [uv, "pip", "install", "--python", str(python)] if uv else [str(python), "-m", "pip", "install"]
        subprocess.run([*install, "mlx-audio==0.6.8"], check=True)
    if not python.is_file():
        raise ValueError("TRUPIC_QWEN_VOICE_PYTHON 应指向已安装 mlx-audio 的解释器")
    if not _qwen_ready():
        model.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            python, "-c",
            "from huggingface_hub import snapshot_download; import sys; "
            "snapshot_download(sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3])",
            QWEN_REPO, QWEN_REVISION, str(model),
        ], check=True)
    for path, digest in (
        ("model.safetensors", "45a5b5ccd3cc473b9d3890ea922937036b56b948e8bd8c678e725329abdd1d00"),
        ("speech_tokenizer/model.safetensors", "836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258"),
    ):
        with (model / path).open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != digest:
                raise RuntimeError(f"Qwen 模型文件校验失败：{path}")
    return model


def _synthesize_qwen(directory, job):
    import fcntl
    import mlx.core as mx
    from mlx_audio.tts.utils import load_model

    # One local model at a time. Process exit releases the lock, including on timeout.
    QWEN_ROOT.mkdir(parents=True, exist_ok=True)
    with (QWEN_ROOT / "inference.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        engine = load_model(_qwen_paths()[0])
        if engine.config.tts_model_type != "custom_voice" or engine.speech_tokenizer is None:
            raise RuntimeError("本地 Qwen 模型缺少 CustomVoice 或语音解码器")
        for index, sentence in enumerate(job["sentences"]):
            # Same seed across style variants makes auditioning direction more informative.
            mx.random.seed(42 + index)
            budget = min(256, max(90, len(sentence) * 8))
            outputs = list(engine.generate(text=sentence, voice=job["speaker"], lang_code="chinese",
                                           instruct=job["directions"][index], temperature=0.75,
                                           max_tokens=budget, verbose=False))
            if len(outputs) != 1 or outputs[0].token_count >= budget:
                raise RuntimeError("Qwen 未完整生成句子")
            _save_line(directory, index, outputs[0].audio, outputs[0].sample_rate)


def _engine_config():
    selected = os.environ.get("TRUPIC_FILM_VOICE_ENGINE", "auto").strip().lower()
    if selected not in {"auto", "kokoro", "qwen3-mlx"}:
        raise ValueError("TRUPIC_FILM_VOICE_ENGINE 支持 auto、kokoro 和 qwen3-mlx")
    if shutil.which("ffmpeg") is None:
        raise ValueError("商品讲解片需要在本机安装 FFmpeg")
    qwen_ready = selected != "kokoro" and _qwen_ready()
    if selected == "qwen3-mlx" or qwen_ready:
        if not qwen_ready:
            raise ValueError("本地 Qwen 中文表达配音尚未就绪。请在 Apple Silicon 上运行 python -m server.film_voice --prepare-qwen")
        style = os.environ.get("TRUPIC_QWEN_VOICE_STYLE", "warm")
        if style not in DIRECTIONS:
            raise ValueError("TRUPIC_QWEN_VOICE_STYLE 支持 warm 和 bright")
        speaker = os.environ.get("TRUPIC_QWEN_VOICE_SPEAKER", "Vivian")
        if speaker.lower() not in {"vivian", "serena", "uncle_fu", "dylan", "eric", "aiden", "ryan", "sohee", "ono_anna"}:
            raise ValueError("请使用 Qwen CustomVoice 的预置音色")
        return {"provider": "qwen3-mlx", "speaker": speaker, "style": style}, _qwen_paths()[1], 240
    try:
        speaker = int(os.environ.get("TRUPIC_FILM_VOICE_SPEAKER") or "59")
    except ValueError as exc:
        raise ValueError("TRUPIC_FILM_VOICE_SPEAKER 应是 3 至 102 的中文音色编号") from exc
    if not 3 <= speaker <= 102:
        raise ValueError("中文 Kokoro 音色编号须在 3 至 102 之间")
    if importlib.util.find_spec("sherpa_onnx") is None or not _model_ready(model_directory()):
        raise ValueError(f"缺少本地 Kokoro 中文神经配音。{PREPARE}")
    return {"provider": PROVIDER, "speaker": speaker}, sys.executable, 90


def ensure_available():
    """Check the same local engine selected by the worker, without loading weights or reserving funds."""
    config, _, _ = _engine_config()
    return config["provider"]


def _voice_job(lines, shots, groups):
    from .merchant_offer import spoken_prices

    config, python, timeout = _engine_config()
    job = dict(config, sentences=[spoken_prices(line) for line in lines])
    if config["provider"] == "qwen3-mlx":
        directions, styles = [], set()
        for shot_index, _, _, indexes in groups:
            if not indexes:
                continue
            chosen = shots[shot_index].get("voiceStyle") or config["style"]
            if chosen not in DIRECTIONS:
                raise ValueError("分镜口播风格须为 warm 或 bright")
            if shot_index == 0:
                role = "开场像朋友轻轻提醒一句。"
            elif shot_index == len(shots) - 1:
                role = "收尾像面对面的邀请，落音干净。"
            else:
                role = "边指给对方看边解释细节，重点词稍停。"
            styles.add(chosen)
            directions.extend([DIRECTIONS[chosen] + role] * len(indexes))
        job.update(style=next(iter(styles)) if len(styles) == 1 else "mixed", directions=directions,
                   shotStyles=[s.get("voiceStyle") or config["style"] for s in shots])
    return job, python, timeout


def _decode(path, *, channels=1, rate=RATE, filters=None, limit=None):
    command = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path)]
    if filters:
        command.extend(["-af", filters])
    if limit is not None:
        command.extend(["-t", str(limit)])
    command.extend(["-ar", str(rate), "-ac", str(channels), "-f", "f32le", "pipe:1"])
    raw = subprocess.run(command, check=True, timeout=45, capture_output=True).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, channels)


def _timecode(seconds):
    total = round(seconds * 1000)
    minutes, ms = divmod(total, 60000)
    hours, minutes = divmod(minutes, 60)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def _timeline(shots, duration):
    previous_end = 0.
    lines = []
    groups = []
    for i, shot in enumerate(shots):
        start, end = float(shot["start"]), float(shot["end"])
        if not (previous_end <= start < end <= duration + 1e-7):
            raise ValueError("配音分镜时间超出成片或互相重叠")
        previous_end = end
        text = str(shot.get("narration") or "").strip()
        parts = [s.strip() for s in SENTENCE.findall(text) if re.search(r"\w", s)]
        if text and not parts:
            raise ValueError(f"第 {i + 1} 镜没有可朗读的文字")
        groups.append((i, start, end, range(len(lines), len(lines) + len(parts))))
        lines.extend(parts)
    if not lines:
        raise ValueError("商品讲解片需要至少一句已定稿的口播")
    if sum(map(len, lines)) > 1200:
        raise ValueError("口播文案超过此短片可容纳的长度")
    return lines, groups


def _place_sentences(temp, lines, groups, duration):
    voice = np.zeros(round(duration * RATE), dtype=np.float32)
    cues = []
    for shot_index, start, end, indexes in groups:
        if not indexes:
            continue
        clips = [_decode(temp / f"line-{idx}.wav")[:, 0] for idx in indexes]
        gap = round(0.13 * RATE)
        cursor = round(start * RATE) + round(0.075 * RATE)
        available = round(end * RATE) - cursor - round(0.045 * RATE) - gap * (len(clips) - 1)
        total = sum(map(len, clips))
        ratio = total / max(available, 1)
        if ratio > 1.18:
            raise ValueError(f"第 {shot_index + 1} 镜口播实测 {total / RATE:.2f} 秒，镜头可用 "
                             f"{max(0, available) / RATE:.2f} 秒，请缩短定稿或延长镜头")
        if ratio > 1:
            # Pitch-preserving tempo correction; no truncation of approved words.
            clips = [_decode(temp / f"line-{idx}.wav", filters=f"atempo={ratio * 1.008:.5f}")[:, 0] for idx in indexes]
        if sum(map(len, clips)) > available + round(0.035 * RATE):
            raise ValueError(f"第 {shot_index + 1} 镜读白无法完整落入镜头，请调整台词")
        for idx, clip in zip(indexes, clips):
            stop = cursor + len(clip)
            voice[cursor:stop] = clip
            cues.append(dict(shotIndex=shot_index, start=round(cursor / RATE, 3),
                             end=round(stop / RATE, 3), text=lines[idx]))
            cursor = stop + gap
    # Tame isolated syllable peaks before raising dialogue to a mobile-friendly level.
    _write_wav(temp / "dry.wav", voice)
    voice = _decode(temp / "dry.wav", filters="acompressor=threshold=0.14:ratio=2.3:attack=6:release=85")[:, 0].copy()
    active = voice[np.abs(voice) > 0.015]
    if not len(active):
        raise RuntimeError("本地配音音量异常")
    # Consistent gain for the entire performance, preserving phrase dynamics.
    voice *= min(0.20 / np.sqrt(np.mean(active ** 2)), 0.87 / np.max(np.abs(voice)))
    return voice, cues


def _mix(temp, bgm_path, duration, cues, *, preserve_voice=False):
    rate = RATE * 2
    frames = round(duration * rate)
    bed = np.zeros((frames, 2), dtype=np.float32)
    source = _decode(bgm_path, channels=2, rate=rate, limit=duration)
    bed[:min(len(source), frames)] = source[:frames]
    rms = np.sqrt(np.mean(bed ** 2))
    if rms > 0:
        bed *= min(0.058 / rms, 3.5, 0.60 / np.max(np.abs(bed)))
    # Duck ~11 dB under words and release between phrases. Overlapping ramps use the lower gain.
    envelope = np.ones(frames, dtype=np.float32)
    for cue in cues:
        a, b = round(cue["start"] * rate), round(cue["end"] * rate)
        first, last = max(0, a - round(0.11 * rate)), min(frames, b + round(0.22 * rate))
        times = np.arange(first, last)
        gain = np.interp(times, [a - 0.11 * rate, a, b, b + 0.22 * rate], [1, 0.28, 0.28, 1])
        np.minimum(envelope[first:last], gain, out=envelope[first:last])
    bed *= envelope[:, None]
    # The mono voice is centered at equal amplitude in both stereo channels.
    mono = _decode(temp / "voice.wav", rate=rate)[:frames]
    if preserve_voice:
        # A merchant-selected take and the unchanged source shots must remain bit-identical.
        # If a peak needs headroom, lower only the backing music.
        backing = bed[:len(mono)]
        limit = np.where(backing >= 0, 0.96 - mono, 0.96 + mono)
        bed *= min(1.0, float((limit / np.maximum(np.abs(backing), 1e-8)).min()))
    mixed = bed.copy()
    mixed[:len(mono)] += mono
    gain = min(1., 0.96 / max(float(np.abs(mixed).max()), 0.001))
    if gain < 1. and not preserve_voice:
        _write_wav(temp / "voice.wav", _decode(temp / "voice.wav")[:, 0] * gain)
    _write_wav(temp / "music-ducked.wav", bed * gain, rate)
    _write_wav(temp / "soundtrack.wav", mixed * gain, rate)


def synthesize_lines(temp, job, python, timeout):
    try:
        process = subprocess.run(
            [python, str(Path(__file__).resolve()), "--synthesize", str(temp)],
            input=json.dumps(job, ensure_ascii=False), text=True, capture_output=True, timeout=timeout,
            env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"本地 {job['provider']} 配音超时，请重试") from exc
    if process.returncode:
        raise RuntimeError(f"{job['provider']} 中文语音合成失败，请检查所选模型、独立运行环境与可用内存")


def write_captions(path, cues):
    srt = "\n\n".join(f"{i}\n{_timecode(c['start'])} --> {_timecode(c['end'])}\n{c['text']}"
                      for i, c in enumerate(cues, 1))
    path.write_text(srt + "\n", encoding="utf-8")


def render_narration(folder, shots, bgm_path, *, duration=None):
    """Align approved per-shot narration and return voice/music/mix paths, measured cues and SRT."""
    folder = Path(folder)
    if not shots:
        raise ValueError("商品讲解片缺少已定稿的分镜")
    duration = float(duration if duration is not None else shots[-1]["end"])
    if not math.isfinite(duration) or not 0 < duration <= 120:
        raise ValueError("商品讲解片时长无效")
    lines, groups = _timeline(shots, duration)
    job, python, timeout = _voice_job(lines, shots, groups)
    folder.mkdir(parents=True, exist_ok=True)
    names = dict(voice="voice.wav", music="music-ducked.wav", mix="soundtrack.wav", subtitles="narration.srt")
    with tempfile.TemporaryDirectory(dir=folder) as work:
        temp = Path(work)
        synthesize_lines(temp, job, python, timeout)
        voice, cues = _place_sentences(temp, lines, groups, duration)
        _write_wav(temp / names["voice"], voice)
        _mix(temp, bgm_path, duration, cues)
        write_captions(temp / names["subtitles"], cues)
        for name in names.values():
            (temp / name).replace(folder / name)
    return {**{k: folder / v for k, v in names.items()}, "cues": cues, "provider": job["provider"], "speaker": job["speaker"],
            "style": job.get("style"), "styleApplied": "directions" in job,
            "shotStyles": job.get("shotStyles", [None for shot in shots])}


if __name__ == "__main__":
    if sys.argv[1:] == ["--prepare"]:
        print(prepare_model())
    elif sys.argv[1:] == ["--prepare-qwen"]:
        print(prepare_qwen())
    elif len(sys.argv) == 3 and sys.argv[1] == "--synthesize":
        job = json.load(sys.stdin)
        if job.get("provider") == "qwen3-mlx":
            _synthesize_qwen(Path(sys.argv[2]), job)
        else:
            _synthesize(Path(sys.argv[2]), job)
    else:
        raise SystemExit("python -m server.film_voice --prepare | --prepare-qwen")
