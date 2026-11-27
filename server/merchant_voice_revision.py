"""Audition a final shot, then keep its exact waveform and the original picture at delivery."""
import hashlib
import json
import math
import re
import shutil
import tempfile
import wave
import zipfile
from pathlib import Path

from . import film_voice as voice


def _sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read_pcm(path):
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, voice.RATE, "NONE"):
            raise ValueError("原作品口播音轨格式不支持局部修改")
        return source.readframes(source.getnframes())


def _write_pcm(path, pcm):
    with wave.open(str(path), "wb") as target:
        target.setparams((1, 2, voice.RATE, 0, "NONE", "NONE"))
        target.writeframes(pcm)


def _shot_job(shots, index, style):
    # Keep real shot position in the director instructions; generate only this shot.
    selected = [dict(s, narration=s.get("narration", "") if n == index else "") for n, s in enumerate(shots)]
    selected[index]["voiceStyle"] = style
    lines, groups = voice._timeline(selected, float(shots[-1]["end"]))
    job, python, timeout = voice._voice_job(lines, selected, groups)
    shot = selected[index]
    length = float(shot["end"]) - float(shot["start"])
    local_groups = [(index, 0.0, length, range(len(lines)))]
    return job, python, timeout, lines, local_groups, length


def _take_spec(shots, style, index):
    job, python, timeout, lines, groups, length = _shot_job(shots, index, style)
    if job["provider"] != "qwen3-mlx":
        raise ValueError("两种片尾读法需要可控制语气的 Qwen 配音模型，请先配置本地表达配音")
    from .merchant_offer import _written_facts

    days, amounts = _written_facts(shots[index]["narration"])
    offer = {"weekday": next(iter(days)), "amount": next(iter(amounts))} if len(days) == len(amounts) == 1 else None
    phrased = [re.sub(r"(?:周|星期)([一二三四五六日天])(到店)[，,]\s*", r"星期\1，\2", line) for line in job["sentences"]]
    if not offer:
        phrased = job["sentences"]
    spec = dict(version=2, provider=job["provider"], model=voice.QWEN_REVISION,
                speaker=job["speaker"], style=style, shotIndex=index, window=[shots[index]["start"], shots[index]["end"]],
                text=shots[index]["narration"], spoken=job["sentences"], phrased=phrased, directions=job["directions"], offer=offer)
    key = hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return key, spec, (job, python, timeout, lines, groups, length)


def _generate_take(folder, generation):
    job, python, timeout, lines, groups, length = generation
    voice.synthesize_lines(folder, job, python, timeout)
    samples, cues = voice._place_sentences(folder, lines, groups, length)
    # Trailing silence is not part of the audition. The full shot window is reassembled in delivery.
    stop = min(len(samples), math.ceil(cues[-1]["end"] * voice.RATE) + round(0.01 * voice.RATE))
    voice._write_wav(folder / "voice.wav", samples[:stop])
    return cues


def _audition(folder, spec, generation):
    from .merchant_offer import require_facts
    from .voice import transcribe

    job, *rest = generation
    variants = [spec["phrased"]]
    if spec["spoken"] != variants[0]:
        variants.append(spec["spoken"])
    for n, words in enumerate(variants):
        try:
            cues = _generate_take(folder, (dict(job, sentences=words), *rest))
            recognized = None
            if spec["offer"]:
                recognized = transcribe((folder / "voice.wav").read_bytes(), folder)
                require_facts(recognized, spec["offer"], "片尾试听", audio=True)
            return cues, recognized
        except ValueError:
            if n == len(variants) - 1:
                raise


def _read_take(cache, key, spec):
    folder = Path(cache) / key
    try:
        meta = json.loads((folder / "take.json").read_text(encoding="utf-8"))
        if meta["spec"] != spec or meta["sha256"] != _sha(folder / "voice.wav"):
            raise ValueError("片尾试听与当前定稿不一致，请重新试听")
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError("找不到该定稿的完整片尾试听，请重新试听") from exc
    return folder / "voice.wav", meta


def preview_ending(cache_folder, shots, style):
    """cache_folder is selected by the caller after checking merchant + revision scope."""
    if not shots or style not in voice.DIRECTIONS:
        raise ValueError("请选择温和或轻快的片尾读法")
    cache = Path(cache_folder)
    cache.mkdir(parents=True, exist_ok=True)
    key, spec, generation = _take_spec(shots, style, len(shots) - 1)
    target = cache / key
    if not target.exists():
        with tempfile.TemporaryDirectory(dir=cache) as work:
            tmp = Path(work)
            cues, recognized = _audition(tmp, spec, generation)
            # A rename publishes only a complete take; simultaneous previews reuse the winning one.
            ready = tmp / "ready"
            ready.mkdir()
            (tmp / "voice.wav").replace(ready / "voice.wav")
            meta = dict(spec=spec, cues=cues, readback=recognized, sha256=_sha(ready / "voice.wav"))
            (ready / "take.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            try:
                ready.rename(target)
            except OSError:
                if not target.is_dir():
                    raise
    audio, meta = _read_take(cache, key, spec)
    with wave.open(str(audio), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
    return dict(audio=audio, takeKey=key, style=style, text=spec["text"], seconds=duration, readback=meta.get("readback"))


def _preserve_mix_windows(folder, source_edit, windows):
    # Global gain and music ducking can vary with the new take. Keep the earlier
    # delivery's actual mix in every locked shot, including any gain it received.
    with zipfile.ZipFile(source_edit) as archive:
        for name in ("soundtrack.wav", "music-ducked.wav"):
            path = folder / name
            with wave.open(str(path), "rb") as revised, archive.open(name) as archived, wave.open(archived, "rb") as old:
                params = revised.getparams()
                if old.getparams()[:4] != params[:4]:
                    # Legacy projects may have a backing track in a different audio format.
                    continue
                pcm = bytearray(revised.readframes(params.nframes))
                stride = params.nchannels * params.sampwidth
                for start, end in windows:
                    a, b = round(start * params.framerate), round(end * params.framerate)
                    old.setpos(a)
                    pcm[a * stride:b * stride] = old.readframes(b - a)
            with wave.open(str(path), "wb") as out:
                out.setparams(params)
                out.writeframes(pcm)


def render_revision(folder, shots, bgm, revision, dims):
    """Use the signed previous edit bundle and a validated, quote-scoped audition."""
    folder = Path(folder)
    frames = round(shots[-1]["end"] * voice.RATE)
    source_edit = revision.get("sourceEdit")
    if source_edit:
        with zipfile.ZipFile(source_edit) as archive:
            timeline = json.loads(archive.read("timeline.json"))
            old_shots = timeline["shots"]
            if (timeline["fps"] != 24 or tuple(timeline["size"]) != tuple(dims)
                    or [(s["startFrame"], s["endFrameExclusive"]) for s in old_shots]
                    != [(s["start"] * 24, s["end"] * 24) for s in shots]):
                raise ValueError("原画面的画幅或镜头时间已变，请重新确认制作方式")
            for name in ("picture.mp4", "voice.wav"):
                with archive.open(name) as source, (folder / name).open("wb") as destination:
                    shutil.copyfileobj(source, destination)
        pcm = bytearray(_read_pcm(folder / "voice.wav"))
        if len(pcm) != frames * 2:
            raise ValueError("原作品声音与镜头时长不符")
    else:
        timeline = {}
        old_shots = [{} for s in shots]
        pcm = bytearray(frames * 2)
    cues = []
    previous = timeline.get("narrator", {})
    config, _, _ = voice._engine_config()
    chosen_key = revision.get("takeKey")
    selected_style = None
    if chosen_key:
        if not re.fullmatch(r"[a-f0-9]{64}", str(chosen_key)):
            raise ValueError("片尾试听标识无效")
        selected_style = revision.get("style")
        if not selected_style:
            try:
                data = json.loads((Path(revision["previewFolder"]) / chosen_key / "take.json").read_text(encoding="utf-8"))
                selected_style = data["spec"]["style"]
            except (OSError, ValueError, KeyError) as exc:
                raise ValueError("该片尾试听已失效") from exc
        if selected_style not in voice.DIRECTIONS:
            raise ValueError("片尾读法无效")
    if previous and (previous["provider"], previous["speaker"]) != (config["provider"], config["speaker"]):
        raise ValueError("当前配音音色与原作品不同，请使用原配音音色修改")
    styles = []
    locked_windows = []
    for i, (shot, original) in enumerate(zip(shots, old_shots)):
        use_take = bool(chosen_key and i == len(shots) - 1)
        style = selected_style if use_take else original.get("voiceStyle") or shot.get("voiceStyle") or config.get("style")
        styles.append(style)
        if not use_take and shot["narration"] == original.get("narration"):
            locked_windows.append((shot["start"], shot["end"]))
            cues.extend(dict(shotIndex=i, start=c["start"], end=c["end"], text=c["text"])
                        for c in timeline["captions"] if c["shotIndex"] == i)
            continue
        start = float(shot["start"])
        first = round(start * voice.RATE) * 2
        last = round(float(shot["end"]) * voice.RATE) * 2
        pcm[first:last] = bytes(last - first)
        if not shot["narration"].strip():
            if use_take:
                raise ValueError("已选片尾与这版台词不匹配，请重新试听")
            continue
        if use_take:
            expected_key, spec, _ = _take_spec(shots, selected_style, i)
            if expected_key != chosen_key:
                raise ValueError("已选片尾与这版台词或镜头不匹配，请重新试听")
            audio, meta = _read_take(revision["previewFolder"], chosen_key, spec)
            clip = _read_pcm(audio)
            new_cues = meta["cues"]
        else:
            with tempfile.TemporaryDirectory(dir=folder) as temp:
                temp = Path(temp)
                new_cues = _generate_take(temp, _shot_job(shots, i, style))
                clip = _read_pcm(temp / "voice.wav")
        if len(clip) > last - first:
            raise ValueError("片尾试听长度超出镜头")
        pcm[first:first + len(clip)] = clip
        cues.extend(dict(c, start=round(c["start"] + start, 3), end=round(c["end"] + start, 3)) for c in new_cues)
    _write_pcm(folder / "voice.wav", pcm)
    voice._mix(folder, bgm, float(shots[-1]["end"]), cues, preserve_voice=True)
    if source_edit and locked_windows:
        _preserve_mix_windows(folder, source_edit, locked_windows)
    voice.write_captions(folder / "narration.srt", cues)
    return dict(voice=folder / "voice.wav", music=folder / "music-ducked.wav", mix=folder / "soundtrack.wav",
                subtitles=folder / "narration.srt", cues=cues, shotStyles=styles,
                **({"picture": folder / "picture.mp4"} if source_edit else {}),
                provider=config["provider"], speaker=config["speaker"], style=styles[0] if len(set(styles)) == 1 else "mixed",
                styleApplied=config["provider"] == "qwen3-mlx")
