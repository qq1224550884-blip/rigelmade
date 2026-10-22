"""Resolution regression checks use generated local fixtures, never paid APIs."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image

import render_core as core


class ImageResolutionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def fixture(self, width, height):
        target = self.root / 'output.png'
        Image.new('RGB', (width, height), 'gray').save(target)
        return target

    def test_legacy_size_also_selects_matching_resolution(self):
        for size, quality in [('2048x1152', 'medium'), ('3840x2160', 'high'), ('2880x2880', 'high')]:
            with self.subTest(size=size):
                req = core.openai_generate_request('gpt-image-2.5', 'test', 1, 'low', size)
                self.assertEqual(req.image_size, quality)
        self.assertEqual(core.resolve_image_quality('high', '1024x1024'), 'high')
        self.assertEqual(core.resolve_image_quality('low', '2016x864'), 'low')

    def test_low_resolution_cannot_pass_as_2k_or_4k(self):
        for tier in ['2K', '4K']:
            with self.subTest(tier=tier), self.assertRaisesRegex(ValueError, '1280.*720'):
                core.validate_output_resolution(core.GenerateRequest(model='gpt-image-2.5', imageSize=tier, aspectRatio='16:9'), self.fixture(1280,720), 'toapis')

    def test_documented_native_dimensions_pass(self):
        for tier, ratio, size in [('2K','16:9',(2048,1152)), ('4K','16:9',(3840,2160)), ('4K','1:1',(2880,2880)), ('4K','9:16',(2160,3840))]:
            with self.subTest(tier=tier, ratio=ratio):
                result = core.validate_output_resolution(core.GenerateRequest(model='gpt-image-2.5', imageSize=tier, aspectRatio=ratio), self.fixture(*size), 'toapis')
                self.assertEqual((result['width'],result['height']),size)

    def test_download_validation_cannot_fall_back_to_remote_url(self):
        target = self.fixture(1280,720)
        data_url = 'data:image/png;base64,' + __import__('base64').b64encode(target.read_bytes()).decode()
        self.enterContext(patch.object(core, 'RUN_DIR', self.root/'runs'))
        self.enterContext(patch.object(core, 'current_api_key', return_value='test-only'))
        self.enterContext(patch.object(core, 'call_toapis', return_value={'data':[{'url':data_url}]}))
        with self.assertRaises(HTTPException) as caught:
            core.generate(core.GenerateRequest(provider='toapis',model='gpt-image-2.5',imageSize='4K',aspectRatio='16:9',prompt='test'))
        self.assertEqual(caught.exception.status_code,502)
        self.assertIn('1280',caught.exception.detail)

    def test_local_edit_preserves_generated_resolution(self):
        source, mask = self.root/'base.png', self.root/'mask.png'
        Image.new('RGB',(1280,720),'gray').save(source)
        alpha=Image.new('RGBA',(1280,720),'white')
        alpha.paste((0,0,0,0),(400,200,800,500))
        alpha.save(mask)
        target = self.fixture(3840,2160)
        Image.new('RGB',(3840,2160),'red').save(target)
        output=core.composite_masked_output(target,[{'role':'main','file':str(source)},{'role':'mask','file':str(mask)}])
        with Image.open(output) as result:
            self.assertEqual(result.size,(3840,2160))
            self.assertEqual(result.getpixel((100,100)),(128,128,128,255))
            self.assertEqual(result.getpixel((1800,1000)),(255,0,0,255))


if __name__ == '__main__':
    unittest.main()
