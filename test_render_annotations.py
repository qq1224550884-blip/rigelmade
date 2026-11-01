"""Annotation interpretation, gating and paid-task contract; no external requests."""
import base64
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException
from PIL import Image

import render_annotations as annotations
import render_core as core


PLAN = {"ready": True, "summary": "左侧加一棵小树", "edits": [{"instruction": "增加1棵小树", "evidence": "黄色树形涂鸦", "sourceImage": 2,
        "location": "左侧蓝色立柱旁", "bbox": [100, 400, 300, 800], "anchor": [200, 800]}], "warnings": []}


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.image = self.root / "guide.png"
        Image.new("RGB", (3840, 2160), "white").save(self.image)
        self.files = [{"file": str(self.image), "role": "main"}, {"file": str(self.image), "role": "annotation"}]
        self.req = core.GenerateRequest(model="gpt-image-2.5-sunburst", provider="toapis", prompt="按黄色涂鸦增加小树",
                                        images=[core.GenerateImage(role="main"), core.GenerateImage(role="annotation")])

    def test_non_annotation_requests_do_not_use_reader(self):
        self.assertFalse(annotations.needed(core.GenerateRequest(prompt="生成涂鸦海报")))
        self.assertFalse(annotations.needed(core.GenerateRequest(prompt="参考图2的材质", images=[core.GenerateImage()])))
        self.assertTrue(annotations.needed(self.req))
        self.assertFalse(annotations.needed(core.GenerateRequest(prompt="提升真实度，不要文字或标注", images=[core.GenerateImage()])))

    def test_coordinates_and_uncertainty_must_not_be_guessed(self):
        for field, value in [("anchor", [1001, 10]), ("anchor", [float("nan"), 10]), ("bbox", [300, 1, 200, 5]), ("sourceImage", 3), ("sourceImage", True)]:
            data = copy.deepcopy(PLAN); data["edits"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError): annotations.validate_plan(data, 2)
        data = copy.deepcopy(PLAN); data["ready"] = False; data["warnings"] = ["文字看不清"]
        with self.assertRaisesRegex(ValueError, "文字看不清"): annotations.validate_plan(data, 2)

    def test_reader_keeps_4k_detail_and_posts_once_with_private_audit(self):
        response = Mock(status_code=200, json=lambda: {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(PLAN)}}], "usage": {"total_tokens": 100}})
        client = Mock(); client.post.return_value = response
        audit = self.root / "private" / "read.json"
        plan = annotations.read(self.req, self.files, "https://example.invalid", "private-test-key", client, audit)
        self.assertEqual(len(plan["edits"]), 1)
        self.assertEqual(client.post.call_count, 1)
        payload = client.post.call_args.kwargs["json"]
        content = payload["messages"][1]["content"]
        self.assertIn("黄色涂鸦", content[0]["text"])
        data = next(part["image_url"] for part in content if part["type"] == "image_url")
        self.assertEqual(data["detail"], "high")
        with Image.open(io.BytesIO(base64.b64decode(data["url"].split(",", 1)[1]))) as image:
            self.assertEqual(image.size, (3840, 2160))
        self.assertNotIn("private-test-key", audit.read_text(encoding="utf-8"))
        self.assertNotIn("data:image", audit.read_text(encoding="utf-8"))

    def test_reader_failure_does_not_retry_or_switch_model(self):
        client = Mock(); client.post.return_value = Mock(status_code=503)
        with self.assertRaisesRegex(ValueError, "HTTP 503"):
            annotations.read(self.req, self.files, "https://example.invalid", "test", client, self.root / "audit.json")
        self.assertEqual(client.post.call_count, 1)

    def test_annotation_upload_does_not_use_material_2k_compression(self):
        # Force byte-limit compression without allocating a giant source image.
        with patch.object(core, "TOAPIS_UPLOAD_MAX_BYTES", 100_000):
            with self.image.open("ab") as handle: handle.write(b" " * 100_000)
            compressed = core.compress_upload_image(self.image, "image/png", preserve_details=True)
        self.assertIsNotNone(compressed)
        with Image.open(compressed[0]) as image: self.assertEqual(image.size, (3840, 2160))

    def _pipeline(self, reader):
        for name, value in [("DATA_DIR", self.root / "data"), ("RUN_DIR", self.root / "data/runs"), ("JOB_STATE_DIR", self.root / "jobs")]:
            self.enterContext(patch.object(core, name, value))
        self.enterContext(patch.object(core, "current_api_key", return_value="test-key"))
        self.enterContext(patch.object(core, "current_base_url", return_value="https://example.invalid"))
        self.enterContext(patch.object(core, "resolve_toapis_base_url", return_value="https://example.invalid"))
        self.enterContext(patch.object(core.annotations, "read", reader))
        image_api = self.enterContext(patch.object(core, "call_toapis", return_value={"id": "only-task"}))
        self.enterContext(patch.object(core, "save_generation_outputs", side_effect=lambda req, run, result, files, provider, progress: {"annotationPlan": progress.data["annotationPlan"]}))
        for image in self.req.images:
            image.data_url = "data:image/png;base64," + base64.b64encode(self.image.read_bytes()).decode()
        return image_api

    def test_reading_precedes_generation_and_plan_survives_task_result(self):
        reader = Mock(return_value=annotations.validate_plan(PLAN, 2))
        image_api = self._pipeline(reader)
        result = core.generate(self.req)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(image_api.call_count, 1)
        self.assertIn("增加1棵小树", image_api.call_args.args[1])
        self.assertIn("(200, 800)", image_api.call_args.args[1])
        self.assertEqual(result["annotationPlan"]["edits"][0]["sourceImage"], 2)

    def test_unclear_annotations_never_start_paid_image_generation(self):
        image_api = self._pipeline(Mock(side_effect=ValueError("字太小看不清，已停止生图")))
        with self.assertRaises(HTTPException): core.generate(self.req)
        image_api.assert_not_called()


if __name__ == "__main__": unittest.main()
