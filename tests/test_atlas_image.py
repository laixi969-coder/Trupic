import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch



class AtlasImageTests(unittest.TestCase):
    def test_download_retry_reuses_prediction_and_does_not_forward_key(self):
        from server import atlas_image

        cfg = dict(url="https://api.atlascloud.ai/api/v1", key="test-key",
                   model="bytedance/seedream-v5.5/text-to-image")
        responses = [
            {"data": {"id": "prediction-1"}},
            *[TimeoutError() for _ in range(3)],
            {"data": {"status": "completed", "outputs": ["https://cdn.example/1.png"]}},
        ]
        with tempfile.TemporaryDirectory() as directory, patch.object(
            atlas_image, "request_json", side_effect=responses
        ) as api, patch.object(atlas_image, "reserve_provider_call") as reserve, patch(
            "urllib.request.build_opener"
        ) as opener, patch.object(atlas_image.time, "sleep"):
            args = cfg, Path(directory), "一只黑猫", 1080, 1440
            with self.assertRaisesRegex(ValueError, "同一张图片"):
                atlas_image.generate(*args)
            response = io.BytesIO(b"image data")
            response.headers = {"Content-Length": "10"}
            opener.return_value.open.side_effect = [ConnectionResetError(), response]
            self.assertEqual(atlas_image.generate(*args), b"image data")
            reserve.assert_called_once_with("image")
            self.assertEqual(api.call_args_list[0].args[2]["size"], "1776*2368")
            self.assertEqual(api.call_args_list[1], api.call_args_list[2])
            request = opener.return_value.open.call_args.args[0]
            self.assertIsNone(request.get_header("Authorization"))
