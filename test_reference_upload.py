"""高像素但体积很小的参考图也必须在上传前处理。"""
import io
import tempfile
import unittest
from pathlib import Path
from PIL import Image

import render_core as core


class ReferenceUploadTests(unittest.TestCase):
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
