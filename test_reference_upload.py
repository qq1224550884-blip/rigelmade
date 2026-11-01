"""高像素但体积很小的参考图也必须在上传前处理。"""
import io
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image

import render_core as core


class ReferenceUploadTests(unittest.TestCase):
    def test_annotation_prompt_is_not_downgraded_to_style_reference(self):
        images = [core.GenerateImage(role="main"), core.GenerateImage(role="reference")]
        for text in ("按照图二写的修改意见修改图一", "黄色涂鸦生成小树，红色圈出的位置增加座椅"):
            with self.subTest(prompt=text):
                prompt = core.build_prompt(core.GenerateRequest(prompt=text, images=images), "toapis")
                self.assertIn(text, prompt)
                self.assertIn("including Chinese text", prompt)
                self.assertIn("location guides for the base image", prompt)
                self.assertIn("merely removing the marks", prompt)
                self.assertNotIn("Resolve conflicts in favor of Image 1", prompt)

    def test_ordinary_reference_prompt_keeps_existing_priority(self):
        req = core.GenerateRequest(prompt="参考图二的木材材质", images=[core.GenerateImage(), core.GenerateImage()])
        self.assertNotIn("ANNOTATION EDIT INSTRUCTIONS", core.build_prompt(req))
        self.assertIn("Resolve conflicts in favor of Image 1", core.build_prompt(req))
        self.assertNotIn("ANNOTATION EDIT INSTRUCTIONS", core.build_prompt(core.GenerateRequest(prompt="生成涂鸦海报")))

    def test_three_reference_bytes_order_and_actual_model_are_audited(self):
        # 真实上传函数 + 假 HTTP：检查发送字节与顺序，不发出收费请求。
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            files = []
            for index, color in enumerate(("gray", "yellow", "green")):
                path = root / f"image-{index}.png"
                Image.new("RGB", (64, 36), color).save(path)
                files.append({"file": str(path), "role": "main" if index == 0 else "reference", "mime": "image/png"})
            uploaded_hashes = []
            payloads = []
            def fake_post(url, **kwargs):
                if "files" in kwargs:
                    _, handle, _ = kwargs["files"]["file"]
                    uploaded_hashes.append(hashlib.sha256(handle.read()).hexdigest())
                    return Mock(status_code=200, json=lambda: {"url": f"https://example.test/{len(uploaded_hashes)}.png"})
                payloads.append(kwargs["json"])
                return Mock(status_code=200, json=lambda: {"id": "fixture"})
            client = Mock()
            client.post.side_effect = fake_post
            client.get.return_value = Mock(status_code=200, json=lambda: {
                "status": "completed", "result": {"data": [{"url": "https://example.test/result.png"}]}})
            req = core.GenerateRequest(model="gpt-image-2.5", prompt="按图二涂鸦修改图一", aspectRatio="16:9", imageSize="2K")
            audit = root / "upstream-request.json"
            with patch.object(core, "resolve_toapis_base_url", return_value="https://example.test"), \
                 patch.object(core, "toapis_http_client", return_value=client), patch.object(core.time, "sleep"):
                core.call_toapis(req, req.prompt, files, "not-a-real-key", "", audit)
            self.assertEqual(uploaded_hashes, [hashlib.sha256(Path(item["file"]).read_bytes()).hexdigest() for item in files])
            self.assertEqual(len(payloads), 1)
            self.assertEqual(payloads[0]["reference_images"], [f"https://example.test/{i}.png" for i in (1, 2, 3)])
            recorded = json.loads(audit.read_text(encoding="utf-8"))
            self.assertEqual(recorded["upstreamModel"], "gpt-image-2.5-flare")
            self.assertEqual(recorded["imageCount"], 3)
            self.assertEqual(recorded["imageOrder"], ["main", "reference", "reference"])
            self.assertEqual(recorded["prompt"], payloads[0]["prompt"])
            self.assertNotIn("not-a-real-key", audit.read_text(encoding="utf-8"))
            self.assertNotIn("https://", audit.read_text(encoding="utf-8"))

    def test_gpt_image_25_uses_current_reference_contract(self):
        client = Mock()
        client.post.return_value = Mock(status_code=200, json=lambda: {"id": "fixture"})
        client.get.return_value = Mock(status_code=200, json=lambda: {
            "status": "completed", "result": {"data": [{"url": "https://example.test/output.png"}]},
        })
        files = [{"file": "main.png", "role": "main"}, {"file": "reference.png", "role": "reference"}]
        with patch.object(core, "resolve_toapis_base_url", return_value="https://example.test"), \
             patch.object(core, "toapis_http_client", return_value=client), \
             patch.object(core, "toapis_upload_image", side_effect=lambda a, k, p, m, c, **kw: "https://example.test/" + p.name), \
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
