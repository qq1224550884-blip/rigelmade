"""高像素但体积很小的参考图也必须在上传前处理。"""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image

import render_core as core


class ReferenceUploadTests(unittest.TestCase):
    def test_gpt_image_25_uses_current_reference_contract(self):
        client = Mock()
        client.post.return_value = Mock(status_code=200, json=lambda: {"id": "fixture"})
        client.get.return_value = Mock(status_code=200, json=lambda: {
            "status": "completed", "result": {"data": [{"url": "https://example.test/output.png"}]},
        })
        files = [{"file": "main.png", "role": "main"}, {"file": "reference.png", "role": "reference"}]
        with patch.object(core, "resolve_toapis_base_url", return_value="https://example.test"), \
             patch.object(core, "toapis_http_client", return_value=client), \
             patch.object(core, "toapis_upload_image", side_effect=lambda a, k, p, m, c: "https://example.test/" + p.name), \
             patch.object(core.time, "sleep"):
            core.call_toapis(core.GenerateRequest(model="gpt-image-2.5", imageSize="low", aspectRatio="16:9"), "test", files, "not-a-real-key", "")
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(payload["reference_images"], ["https://example.test/main.png", "https://example.test/reference.png"])
        self.assertEqual((payload["resolution"], payload["quality"], payload["size"]), ("1K", "high", "16:9"))
        self.assertNotIn("metadata", payload)

    def test_large_pixel_png_is_resized_even_below_byte_limit(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "large.png"
            with Image.new("RGBA", (10240, 5760), "white") as original:
                original.save(path)
            self.assertLess(path.stat().st_size, core.TOAPIS_UPLOAD_MAX_BYTES)
            buffer, name, mime = core.compress_upload_image(path, "image/png")
            self.assertEqual((name, mime), ("upload.jpg", "image/jpeg"))
            with Image.open(io.BytesIO(buffer.getvalue())) as result:
                self.assertEqual(result.size, (2048, 1152))
            with Image.open(path) as original:
                self.assertEqual(original.size, (10240, 5760))

    def test_regular_reference_and_transparent_mask_pass_through(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "mask.png"
            with Image.new("RGBA", (1600, 900), (255, 255, 255, 0)) as image:
                image.save(path)
            self.assertIsNone(core.compress_upload_image(path, "image/png"))


if __name__ == "__main__":
    unittest.main()
