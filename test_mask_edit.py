"""No paid requests: alpha-mask validation and ToAPIs payload contract."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image
import render_core as core


class MaskEditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        Image.new('RGB', (32, 18), 'gray').save(self.root / 'base.png')
        Image.new('RGB', (8, 8), 'tan').save(self.root / 'material.png')
        mask = Image.new('RGBA', (32, 18), 'white')
        mask.putpixel((10, 10), (255, 255, 255, 0))
        mask.save(self.root / 'mask.png')
        self.files = [{'role': role, 'file': str(self.root / name)} for role, name in
                      [('main', 'base.png'), ('reference', 'material.png'), ('mask', 'mask.png')]]

    def test_mask_contract_and_reference_order(self):
        client = Mock()
        client.post.return_value = Mock(status_code=200, json=lambda: {'id': 'task-test'})
        client.get.return_value = Mock(status_code=200, json=lambda: {
            'status': 'completed', 'result': {'data': [{'url': 'https://example.test/result.png'}]}})
        with patch.object(core, 'resolve_toapis_base_url', return_value='https://example.test'), \
             patch.object(core, 'toapis_http_client', return_value=client), \
             patch.object(core, 'toapis_upload_image', side_effect=lambda a, k, p, m, c: 'https://example.test/' + p.name), \
             patch.object(core.time, 'sleep'):
            core.call_toapis(core.GenerateRequest(model='gpt-image-2'), 'edit', self.files, 'test', '')
        payload = client.post.call_args.kwargs['json']
        self.assertEqual(payload['image_urls'], ['https://example.test/base.png', 'https://example.test/material.png'])
        self.assertEqual(payload['mask_url'], 'https://example.test/mask.png')
        self.assertEqual(payload['size'], '16:9')
        self.assertEqual(client.post.call_count, 1)

    def test_unknown_mask_capability_rejected(self):
        with self.assertRaisesRegex(ValueError, '不会自动换模型'):
            core.validate_toapis_mask('unknown-model', self.files)

    def test_wrong_dimensions_rejected(self):
        Image.new('RGBA', (8, 8), (0, 0, 0, 0)).save(self.root / 'mask.png')
        with self.assertRaisesRegex(ValueError, '尺寸一致'):
            core.validate_toapis_mask('gpt-image-2', self.files)

    def test_empty_selection_rejected(self):
        Image.new('RGBA', (32, 18), 'white').save(self.root / 'mask.png')
        with self.assertRaisesRegex(ValueError, '没有透明'):
            core.validate_toapis_mask('gpt-image-2', self.files)

    def test_no_mask_does_not_restrict_regular_generation(self):
        self.assertIsNone(core.validate_toapis_mask('gpt-image-2.5-sunburst', self.files[:2]))

    def test_sunburst_selection_guide_and_pixel_preservation(self):
        core.validate_toapis_mask('gpt-image-2.5-sunburst', self.files)
        guide = core.create_selection_guide(self.root / 'base.png', self.root / 'mask.png')
        with Image.open(guide) as image:
            self.assertEqual(image.getpixel((0, 0)), (128, 128, 128))
            self.assertNotEqual(image.getpixel((10, 10)), (128, 128, 128))
        Image.new('RGB', (64, 36), 'red').save(self.root / 'result.png')
        output = core.composite_masked_output(self.root / 'result.png', self.files)
        with Image.open(output) as image:
            self.assertEqual(image.size, (64, 36))
            self.assertEqual(image.getpixel((0, 0)), (128, 128, 128, 255))
            self.assertEqual(image.getpixel((20, 20)), (255, 0, 0, 255))

    def test_sunburst_payload_uses_guide_not_unverified_mask_field(self):
        client = Mock()
        client.post.return_value = Mock(status_code=200, json=lambda: {'id': 'task-test'})
        client.get.return_value = Mock(status_code=200, json=lambda: {
            'status': 'completed', 'result': {'data': [{'url': 'https://example.test/result.png'}]}})
        with patch.object(core, 'resolve_toapis_base_url', return_value='https://example.test'), \
             patch.object(core, 'toapis_http_client', return_value=client), \
             patch.object(core, 'toapis_upload_image', side_effect=lambda a, k, p, m, c: 'https://example.test/' + p.name), \
             patch.object(core.time, 'sleep'):
            core.call_toapis(core.GenerateRequest(model='gpt-image-2.5-sunburst'), 'edit', self.files, 'test', '')
        payload = client.post.call_args.kwargs['json']
        self.assertNotIn('mask_url', payload)
        self.assertEqual(payload['reference_images'][-1], 'https://example.test/selection-guide.png')
        self.assertEqual(len(payload['reference_images']), 3)
        self.assertIn('LAST attachment', payload['prompt'])

    def test_wrong_output_ratio_rejected(self):
        Image.new('RGB', (32, 32), 'red').save(self.root / 'result.png')
        with self.assertRaisesRegex(ValueError, '画幅'):
            core.composite_masked_output(self.root / 'result.png', self.files)

    def test_oversized_mask_is_not_lossily_compressed(self):
        with patch.object(core, 'TOAPIS_UPLOAD_MAX_BYTES', 1), self.assertRaisesRegex(ValueError, '上传上限'):
            core.validate_toapis_mask('gpt-image-2', self.files)


if __name__ == '__main__':
    unittest.main()
