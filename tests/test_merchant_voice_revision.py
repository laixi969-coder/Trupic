import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import wave
import zipfile
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from server import film_voice as v
from server.media import render
from server.merchant_voice_revision import preview_ending, render_revision


def pcm(wav):
    with wave.open(io.BytesIO(wav), "rb") as stream:
        return stream.readframes(stream.getnframes())


def synth(folder, job, python, timeout):
    for i, (words, direction) in enumerate(zip(job["sentences"], job["directions"])):
        pitch = 220 + sum(map(ord, words)) % 60
        bright = v.DIRECTIONS["bright"] in direction
        length = 1.2 if bright else 0.9
        times = np.arange(round(length * v.RATE)) / v.RATE
        waveform = np.sin(2 * np.pi * (pitch + 50 * bright) * times) * 0.25
        v._write_wav(folder / f"line-{i}.wav", waveform)


class EndingRevisionTest(unittest.TestCase):
    def test_wrong_weekday_is_retried_and_never_cached(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            v, "_engine_config", return_value=({"provider":"qwen3-mlx", "speaker":"Vivian", "style":"warm"}, "python", 30)
        ), patch.object(v, "synthesize_lines", side_effect=synth) as calls, patch(
            "server.voice.transcribe", return_value="中午到店，十九块九。"
        ):
            shots = [dict(start=0, end=3, narration="看看杯壁。"), dict(start=3, end=8, narration="周五到店，19.90元。")]
            with self.assertRaisesRegex(ValueError, "片尾试听"):
                preview_ending(tmp, shots, "bright")
            self.assertEqual([c.args[1]["sentences"] for c in calls.call_args_list],
                             [["星期五，到店十九块九。"], ["周五到店，十九块九。"]])
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_selected_take_source_picture_and_unchanged_stems_survive_delivery(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, TRUPIC_VIDEO_RENDERER="ffmpeg"), patch.object(
            v, "_engine_config", return_value=({"provider": "qwen3-mlx", "speaker": "Vivian", "style": "warm"}, "python", 30)
        ), patch.object(v, "synthesize_lines", side_effect=synth) as calls, patch(
            "server.voice.transcribe", return_value="星期五到店，十九块九。") as readbacks:
            root = Path(tmp)
            source = root / "product.png"
            image = Image.new("RGB", (160, 160), "#ddd4aa")
            ImageDraw.Draw(image).rectangle((32, 10, 110, 99), fill="#33674f")
            image.save(source)
            output = dict(width=288, height=512, dpi=72, duration=15)
            plan = dict(original="展示抹茶", profile={"name":"茶铺"}, subject="抹茶", output=output, productNarration=True)
            shots = [
                dict(start=0, end=3, camera="近景", line="看看杯壁", caption="", narration="看看杯壁。"),
                dict(start=3, end=10, camera="细节", line="抹茶和牛奶", caption="", narration="抹茶和牛奶分层。"),
                dict(start=10, end=15, camera="全景", line="周五到店", caption="", narration="周五到店，18.90元一杯。"),
            ]
            original = root / "original"
            cp = dict(title="抹茶", body="抹茶和牛奶", cta="周五到店", storyboard=shots)
            render(original, plan, cp, "video", source, "story", 0)
            before = original / "edit.zip"
            revised = [dict(s) for s in shots]
            revised[-1]["narration"] = "周五到店，19.90元一杯。"
            cache = root / "offers"
            warm = preview_ending(cache, revised, "warm")
            bright = preview_ending(cache, revised, "bright")
            self.assertNotEqual(warm["takeKey"], bright["takeKey"])
            self.assertNotEqual(warm["audio"].read_bytes(), bright["audio"].read_bytes())
            self.assertNotIn("19.90", calls.call_args.args[1]["sentences"][0])
            self.assertEqual(readbacks.call_count, 2)
            self.assertEqual(bright["readback"], "星期五到店，十九块九。")
            calls.reset_mock()
            self.assertEqual(bright, preview_ending(cache, revised, "bright"))
            cfg = dict(sourceEdit=before, previewFolder=cache, takeKey=bright["takeKey"])
            after = root / "delivery"
            render(after, {**plan, "_filmRevision": cfg}, {**cp, "storyboard": revised}, "video", source, "story", 0)
            calls.assert_not_called()
            with zipfile.ZipFile(before) as a, zipfile.ZipFile(after / "edit.zip") as b, zipfile.ZipFile(after / "open-design.zip") as project:
                self.assertEqual(a.read("picture.mp4"), b.read("picture.mp4"))
                self.assertEqual(a.read("picture.mp4"), project.read("assets/picture.mp4"))
                old, new = pcm(a.read("voice.wav")), pcm(b.read("voice.wav"))
                end_start = 10 * v.RATE * 2
                self.assertEqual(old[:end_start], new[:end_start])
                for track in ("music-ducked.wav", "soundtrack.wav"):
                    with wave.open(io.BytesIO(a.read(track)), "rb") as first, wave.open(io.BytesIO(b.read(track)), "rb") as second:
                        self.assertEqual(first.readframes(10 * first.getframerate()), second.readframes(10 * second.getframerate()))
                take = pcm(bright["audio"].read_bytes())
                self.assertEqual(take, new[end_start:end_start + len(take)])
                self.assertFalse(any(new[end_start + len(take):]))
                self.assertNotEqual(old[end_start:], new[end_start:])
                self.assertIn("19.90元", b.read("captions.srt").decode())
                self.assertNotIn("18.90", b.read("captions.srt").decode())
                time = json.loads(b.read("timeline.json"))
                self.assertEqual([s["voiceStyle"] for s in time["shots"]], ["warm", "warm", "bright"])
                self.assertEqual(time["captions"][:2], json.loads(a.read("timeline.json"))["captions"][:2])
                self.assertEqual(b.read("voice.wav"), project.read("assets/voice.wav"))

            # The exact same key cannot approve different commercial terms.
            with self.assertRaisesRegex(ValueError, "不匹配"):
                render_revision(after, shots, after / "unused.wav", cfg, (288, 512))
            calls.assert_not_called()
            # Price-only revision synthesizes just the edited, previously warm ending.
            from server.media import soundtrack
            bed = root / "bed.wav"
            soundtrack(bed, duration=15, cuts=[0, 3, 10])
            info = render_revision(after, revised, bed, {"sourceEdit": before}, (288, 512))
            self.assertEqual(info["shotStyles"], ["warm", "warm", "warm"])
            self.assertEqual(calls.call_count, 1)
            self.assertEqual(calls.call_args.args[1]["style"], "warm")
