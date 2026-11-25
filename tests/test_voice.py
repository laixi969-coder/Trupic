import io
import os
import shutil
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase, skipUnless
from unittest.mock import patch

from test_workflows import studio
from server import voice


API = "/api/agent/voice"


def upload(client, data):
    # Both the claimed MIME and filename are deliberately unrelated to the actual bytes.
    response = client.post(API + "/transcribe", data={"audio": (io.BytesIO(data), "input.dat", "text/plain")})
    response.request.input_stream.close()
    return response


def silent_wav(seconds):
    output = io.BytesIO()
    with wave.open(output, "wb") as out:
        out.setparams((1, 2, voice.RATE, 0, "NONE", "not compressed"))
        out.writeframes(bytes(2 * voice.RATE * seconds))
    return output.getvalue()


class VoiceTests(TestCase):
    def setUp(self):
        self.client = studio.app.test_client()
        self.tenant = self.client.get("/api/state").json["workspace"]

    def test_rollout_cross_origin_and_size_limits(self):
        for route in ("/speak", "/transcribe"):
            with patch.dict(os.environ, {"TRUPIC_PERSONAL_AGENT": "0"}):
                self.assertEqual(self.client.post(API + route).status_code, 403)
            self.assertEqual(self.client.post(API + route, headers={"Origin": "https://other.test"}).status_code, 403)
        self.assertEqual(upload(self.client, b"").status_code, 400)
        self.assertEqual(self.client.post(API + "/transcribe").status_code, 400)
        for size in (voice.MAX_AUDIO_BYTES + 1, voice.MAX_AUDIO_BYTES + 100_000):
            large = upload(self.client, bytes(size))
            self.assertEqual(large.status_code, 413)
            self.assertIn("录音", large.json["error"])
        self.assertEqual(self.client.post(API + "/speak", json={"text": "好" * 601}).status_code, 400)

    @skipUnless(shutil.which("ffmpeg"), "requires FFmpeg")
    def test_invalid_silent_and_long_recordings_never_reach_whisper(self):
        # These must yield an audio error even if no Whisper model is installed.
        with patch.dict(os.environ, {"TRUPIC_WHISPER_MODEL": "/absent/voice-model"}):
            for data, message in ((b"unrelated file", "解码"), (silent_wav(1), "人声"), (silent_wav(61), "60 秒")):
                response = upload(self.client, data)
                self.assertEqual(response.status_code, 422, response.json)
                self.assertIn(message, response.json["error"])

    def test_transcription_returns_only_text_and_cleans_up(self):
        dirs = []

        def recognize(data, folder):
            self.assertEqual(data, b"sample")
            dirs.append(folder)
            (folder / "input").write_bytes(data)
            return "选第二组"

        with patch.object(voice, "transcribe", recognize):
            response = upload(self.client, b"sample")
        self.assertEqual(response.json, {"text": "选第二组"})
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertFalse(dirs[0].exists())

    def test_workspace_shares_one_slot_and_other_workspaces_can_play(self):
        started, finish = threading.Event(), threading.Event()

        def synthesize(text, _):
            if text == "等待":
                started.set()
                finish.wait(5)
            return b"mp3"

        def play():
            client = studio.app.test_client()
            with client.session_transaction() as sess:
                sess["tenant"] = self.tenant
            return client.post(API + "/speak", json={"text": "等待"})

        with patch.object(voice, "speak", synthesize), ThreadPoolExecutor(1) as pool:
            future = pool.submit(play)
            try:
                self.assertTrue(started.wait(4))
                self.assertEqual(upload(self.client, b"something").status_code, 429)
                other = studio.app.test_client().post(API + "/speak", json={"text": "另一个空间"})
                self.assertEqual((other.status_code, other.mimetype), (200, "audio/mpeg"))
            finally:
                finish.set()
            self.assertEqual(future.result().data, b"mp3")

    @skipUnless(os.getenv("TRUPIC_TEST_VOICE_LIVE") == "1", "requires local Mandarin voice and multilingual Whisper model")
    def test_real_chinese_round_trip(self):
        source = self.client.post(API + "/speak", json={"text": "选第二组。"})
        self.assertEqual((source.status_code, source.mimetype), (200, "audio/mpeg"))
        self.assertGreater(len(source.data), 1000)
        response = upload(self.client, source.data)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertIn("第二组", response.json["text"])
