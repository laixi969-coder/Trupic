"""Render an isolated product film and check subtitles, editable tracks and encoded media."""

import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
import wave
import zipfile
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from server.media import render
from server.visual_review import inspect_export, spoken_at


def fixture_audio(folder, shots, bgm, *, duration):
    rate = 24000
    voice = np.zeros(rate * duration)
    cues = []
    for index, shot in enumerate(shots):
        start = shot["start"] + 0.125
        end = start + 1.25
        times = np.arange(round((end-start)*rate)) / rate
        voice[round(start*rate):round(end*rate)] = np.sin(2*np.pi*(220+50*index)*times) * 0.2
        cues.append(dict(shotIndex=index, text=shot["narration"], start=start, end=end))
    bed = np.sin(2*np.pi*87*np.arange(len(voice))/rate) * 0.04
    files = {}
    for key, samples in (("voice", voice), ("music", bed), ("mix", voice+bed)):
        files[key] = folder / f"{key}.wav"
        with wave.open(str(files[key]), "wb") as out:
            out.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            out.writeframes((samples*32767).astype("<i2").tobytes())
    files["subtitles"] = folder / "narration.srt"
    files["subtitles"].write_text("\n\n".join(
        f"{i+1}\n00:00:{s['start']:02d},125 --> 00:00:{s['start']+1:02d},375\n{s['narration']}" for i,s in enumerate(shots)
    ) + "\n", encoding="utf-8")
    return dict(files, provider="test", speaker=3, cues=cues)


class NarratedRenderTests(unittest.TestCase):
    def test_measured_captions_and_replaceable_tracks_match_export(self):
        self.check_export(moving_background=False)

    def test_moving_background_project_contains_the_actual_clean_video(self):
        self.check_export(moving_background=True)

    def test_background_revision_preserves_master_subject_audio_and_overlay_layers(self):
        self.check_export(moving_background=False, background_revision=True)

    def check_export(self, moving_background, background_revision=False):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, TRUPIC_VIDEO_RENDERER="ffmpeg"):
            root = Path(temp)
            source = root / "product.png"
            product = Image.new("RGB", (160, 160), "#e5d29b")
            draw = ImageDraw.Draw(product)
            draw.rectangle((33,10,128,84),fill="#2b6856")
            draw.ellipse((54,23,108,70),fill="#cf967e")
            product.save(source)
            output = dict(width=288,height=512,dpi=72,duration=15)
            plan = dict(original="试拍这只茶盒", profile={"name":"茶铺"}, subject="茶盒", output=output, productNarration=True)
            if moving_background or background_revision:
                sequence = root / "cloud-frames"
                sequence.mkdir()
                plates = []
                for shade in ("#889196", "#8a9697"):
                    plate = root / f"{len(plates)}.jpg"
                    Image.new("RGB", (output["width"], output["height"]), shade).save(plate)
                    plates.append(plate)
                for i in range(360):
                    os.link(plates[i // 30 % 2], sequence / f"{i + 1:03d}.jpg")
                if moving_background:
                    plan["videoBackground"] = str(sequence)
            shots = [
                dict(start=0,end=3,camera="近景",line="看看茶盒",caption="",narration="看看茶盒。"),
                dict(start=3,end=10,camera="细节",line="盒身",caption="",narration="看这里的细节。",
                     evidence={"label":"圆形标签","region":[0.32,0.31,0.70,0.65]}),
                dict(start=10,end=15,camera="全景",line="门店可见",caption="仅限堂食",narration="欢迎来看看。"),
            ]
            copy = dict(title="看看茶盒",body="盒身可见",cta="门店可见",storyboard=shots)
            with patch("server.film_voice.render_narration", side_effect=fixture_audio):
                layout = render(root, plan, copy, "video", source, "story", 0)
            self.assertEqual([], inspect_export(root, layout, source, source, None, copy, output))
            first = layout["frames"][1]
            self.assertIsNone(spoken_at(first, 2))
            self.assertEqual(spoken_at(first, 3)["text"], shots[0]["narration"])
            self.assertIsNone(spoken_at(first, 33))
            self.assertNotIn("看看茶盒", [item[3] for item in first["text"]])
            with zipfile.ZipFile(root/"edit.zip") as edit, zipfile.ZipFile(root/"open-design.zip") as project:
                if moving_background:
                    self.assertEqual(edit.read("picture.mp4"), project.read("assets/picture.mp4"))
                    self.assertIn('src="assets/picture.mp4"', project.read("index.html").decode())
                srt = (root/"captions.srt").read_bytes()
                self.assertEqual(edit.read("captions.srt"), srt)
                self.assertEqual(project.read("captions.srt"), srt)
                self.assertIn(b"00:00:00,125 --> 00:00:01,375", srt)
                for name in ("voice.wav", "music-ducked.wav", "soundtrack.wav"):
                    self.assertEqual(edit.read(name), project.read("assets/"+name))
                timeline = json.loads(edit.read("timeline.json"))
                self.assertEqual(timeline["captions"][0]["endFrame"], 33)
                self.assertIn('data-track-kind="captions" src="assets/spoken-1.png"', project.read("index.html").decode())
            if background_revision:
                revised = root / "revised"
                revised_plan = dict(plan, videoBackground=str(sequence), _filmRevision={"backgroundArchive": root/"edit.zip"})
                with patch("server.film_voice.render_narration", side_effect=AssertionError("locked voice must be reused")):
                    result = render(revised, revised_plan, copy, "video", source, "story", 0)
                self.assertEqual([], inspect_export(revised, result, source, source, None, copy, output))
                with zipfile.ZipFile(root/"edit.zip") as before, zipfile.ZipFile(revised/"edit.zip") as after:
                    for name in before.namelist():
                        if name.endswith((".png", ".wav", ".srt", ".edl")) or name == "timeline.json":
                            self.assertEqual(before.read(name), after.read(name), name)
                def decode(folder):
                    raw = subprocess.check_output(["ffmpeg","-v","error","-ss","1","-i",str(folder/"video.mp4"),
                                                   "-frames:v","1","-f","rawvideo","-pix_fmt","rgb24","pipe:1"])
                    return np.frombuffer(raw,dtype=np.uint8).reshape((512,288,3)).astype(float)
                delta = np.abs(decode(root) - decode(revised))
                self.assertLess(delta[240:320,120:175].mean(), 3.0)
                self.assertGreater(delta[:48].mean(), 10.0)
