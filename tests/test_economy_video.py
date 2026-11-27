"""The low-cost Atlas route stays local to a task and uses its published T2V schema."""

import unittest
from unittest.mock import patch


class EconomyVideoTests(unittest.TestCase):
    def test_config_uses_exact_catalogued_model_and_omits_backup(self):
        from server import video_api as video

        cfg = {
            "provider": "atlas",
            "protocol": "atlas-video",
            "url": video.providers.DEFAULT_URLS["atlas", "video"],
            "key": "test-key",
            "model": "configured-model",
            "backup": {"model": "other-provider"},
        }
        with (
            patch.object(video.model, "route", return_value=cfg),
            patch.object(video, "db") as db,
            patch.object(video.providers, "require_catalog_model") as verify,
            patch.object(video.model_admission, "formal", return_value=True),
            patch.object(
                video.model_admission, "eligible", return_value=True
            ) as eligible,
        ):
            selected = video.economy_config()
            self.assertEqual(selected["model"], video.ECONOMY_MODEL)
            self.assertNotIn("backup", selected)
            self.assertEqual(cfg["model"], "configured-model")
            verify.assert_called_once_with(
                db.return_value.__enter__.return_value, "atlas", "video", selected
            )
            eligible.assert_called_once_with(
                db.return_value.__enter__.return_value, "video", selected
            )
            eligible.return_value = False
            with self.assertRaisesRegex(ValueError, "准入"):
                video.economy_config()
            cfg["url"] = "https://some-other-provider.invalid/"
            with self.assertRaisesRegex(ValueError, "Atlas"):
                video.economy_config()

    def test_h3_payload_and_polling_match_schema(self):
        from server import video_api as video

        cfg = {
            "model": video.ECONOMY_MODEL,
            "url": video.providers.DEFAULT_URLS["atlas", "video"],
            "protocol": "atlas-video",
        }
        responses = [
            {"data": {"id": "test-task"}},
            {
                "data": {
                    "status": "completed",
                    "outputs": ["https://media.invalid/result.mp4"],
                }
            },
        ]
        with patch.object(video, "request_json", side_effect=responses) as request:
            self.assertEqual(video.submit(cfg, "柜台背景", "9:16"), "test-task")
            status, url = video.poll_task(cfg, "test-task")
        self.assertEqual(
            (status, url), ("completed", "https://media.invalid/result.mp4")
        )
        self.assertEqual(
            request.call_args_list[0].args,
            (
                cfg,
                cfg["url"],
                {
                    "model": video.ECONOMY_MODEL,
                    "prompt": "柜台背景",
                    "ratio": "9:16",
                    "resolution": "480P",
                    "duration": 9,
                    "prompt_expansion": False,
                },
            ),
        )
        self.assertEqual(
            request.call_args_list[1].args[1],
            "https://api.atlascloud.ai/api/v1/model/prediction/test-task",
        )

    def test_one_remote_clip_fills_fifteen_seconds_and_retry_reuses_it(self):
        import shutil
        import subprocess
        import tempfile
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path

        from server import video_api as video

        cfg = {
            "model": video.ECONOMY_MODEL,
            "url": video.providers.DEFAULT_URLS["atlas", "video"],
            "protocol": "atlas-video",
            "provider": "atlas",
        }
        plan = {
            "output": {"width": 72, "height": 128, "duration": 15},
            "coordination": {"product": "抹茶拿铁", "concept": "柜台光线"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "simulated-provider-output.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=s=72x128:r=12",
                    "-t",
                    "9",
                    "-pix_fmt",
                    "yuv420p",
                    str(source),
                ],
                check=True,
            )
            with (
                patch.object(video, "submit", return_value="fixture-task") as submit,
                patch.object(
                    video,
                    "poll_task",
                    return_value=("completed", "https://fixture.invalid/movie.mp4"),
                ),
                patch.object(
                    video,
                    "download",
                    side_effect=lambda _, path: shutil.copyfile(source, path),
                ),
                patch.object(video.model, "reserve_provider_call") as reserve,
                patch.object(video, "db"),
            ):
                folder = base / "work"
                with ThreadPoolExecutor(max_workers=2) as workers:
                    pair = [
                        workers.submit(
                            video.prepare_background,
                            folder,
                            plan,
                            {"storyboard": []},
                            cfg,
                        )
                        for _ in range(2)
                    ]
                    frames = pair[0].result()
                    self.assertEqual(pair[1].result(), frames)
                self.assertEqual(len(list(frames.glob("*.jpg"))), 360)
                self.assertEqual(plan["videoModel"], video.ECONOMY_MODEL)
                self.assertEqual(
                    video.prepare_background(folder, plan, {"storyboard": []}, cfg),
                    frames,
                )
                # A last frame alone, a corrupted frame, or debris from a longer clip
                # must never certify material that was not decoded for this job.
                (frames / "120.jpg").write_bytes(b"corrupt")
                (frames / "999.jpg").write_bytes(b"stale")
                self.assertEqual(
                    video.prepare_background(folder, plan, {"storyboard": []}, cfg),
                    frames,
                )
                self.assertEqual(len(list(frames.glob("*.jpg"))), 360)
                self.assertNotEqual((frames / "120.jpg").read_bytes(), b"corrupt")
                with self.assertRaisesRegex(ValueError, "另一份制作需求"):
                    video.prepare_background(
                        folder, plan, {"storyboard": [{"camera": "different"}]}, cfg
                    )
                submit.assert_called_once()
                reserve.assert_called_once_with("video")

    def test_only_an_actual_atlas_charge_is_revealed(self):
        from server import video_api as video

        cfg = {
            "protocol": "atlas-video",
            "url": video.providers.DEFAULT_URLS["atlas", "video"],
        }
        row = {"id": "same", "status": "completed", "price": "0.135", "outputs": []}
        for state in ("pending", "charged"):
            paid = {}
            with patch.object(
                video,
                "request_json",
                return_value={"data": dict(row, charge_status=state)},
            ):
                video.poll_task(cfg, "same", paid)
            self.assertEqual(
                paid,
                {"amount": "0.135", "currency": "USD", "field": "price"}
                if state == "charged"
                else {},
            )
        with (
            patch.object(video, "request_json", return_value={"data": row}),
            self.assertRaisesRegex(ValueError, "不匹配"),
        ):
            video.poll_task(cfg, "another", {})
