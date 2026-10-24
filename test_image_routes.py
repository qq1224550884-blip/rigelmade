"""Image route contract and billing tests; no external API requests."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException
from PIL import Image

import render_core as core
import render_routes as routes
import test_render_delivery as delivery_tests


class RouteContractTests(unittest.TestCase):
    def test_fast_uses_documented_official_payload_and_preserves_2k(self):
        client=Mock()
        client.post.return_value=Mock(status_code=200,json=lambda:{'id':'original-task'})
        client.get.return_value=Mock(status_code=200,json=lambda:{'status':'completed','result':{'data':[{'url':'https://example.test/image.png'}]},'billing':{'status':'settled','cost_usd':'0.020528'}})
        req=core.GenerateRequest(model=routes.FAST_MODEL,imageSize='2K',aspectRatio='16:9')
        with patch.object(core,'toapis_http_client',return_value=client),patch.object(core,'resolve_toapis_base_url',return_value='https://example.test'),patch.object(core.time,'sleep'):
            result=core.call_toapis(req,'same prompt',[],'test-key','')
        payload=client.post.call_args.kwargs['json']
        self.assertEqual(payload,{'model':'gpt-image-2.5-flare-official','prompt':'same prompt','quality':'medium','size':'2048x1152','n':1})
        self.assertEqual(result['billing']['cost_usd'],'0.020528')
        self.assertEqual(client.post.call_count,1)

    def test_sunburst_is_allowed_and_retains_normal_contract(self):
        self.assertEqual(core.supported_model('gpt-image-2.5-sunburst'),'gpt-image-2.5-sunburst')
        self.assertEqual(core.toapis_image_model('gpt-image-2.5'),'gpt-image-2.5-flare')
        self.assertIn('gpt-image-2.5-sunburst',core.TOAPIS_TOP_LEVEL_RESOLUTION_MODELS)

    def test_fast_rejects_untested_resolution_multi_reference_and_mask(self):
        for changes in ({'imageSize':'4K'},{'images':[core.GenerateImage(),core.GenerateImage()]},{'images':[core.GenerateImage(role='mask')]},{'count':2},{'prompt':'x'*8001}):
            req=core.GenerateRequest(**({'model':routes.FAST_MODEL,'imageSize':'2K'}|changes))
            with self.assertRaises(HTTPException):routes.validate_fast_request(req)

    def test_preview_input_keeps_aspect_and_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.png'
            Image.new('RGB',(4096,4096)).save(source)
            target=routes.fast_input(source)
            with Image.open(target) as image:
                self.assertEqual(image.width,image.height)
                self.assertLessEqual(image.width*image.height,2_359_296+3072)
            with Image.open(source) as image:self.assertEqual(image.size,(4096,4096))

    def test_settlement_rounds_up_and_never_exceeds_disclosed_cap(self):
        self.assertEqual(routes.preview_credits({'billing':{'status':'settled','cost_usd':'0.020528'}},24),7)
        self.assertEqual(routes.preview_credits({'billing':{'status':'settled','cost_usd':'1'}},24),24)
        for cost in ('NaN','Infinity','-1','0'):
            self.assertIsNone(routes.settled_cost({'billing':{'status':'settled','cost_usd':cost}}))


class RouteBillingTests(delivery_tests.DeliveryJobTests):
    def setUp(self):
        super().setUp()
        with self.gateway.transaction() as db:
            db.execute("INSERT INTO model_prices VALUES(?, 'medium',24,1,0)",(routes.FAST_MODEL,))
        self.client.get.return_value=delivery_tests.Response(data={'status':'completed','result':{'data':[{'url':'https://example.test/original.png'}]},'billing':{'status':'settled','cost_usd':'0.020528'}})

    def fast_start(self,key='fast-task',quality='medium',size='2048x1152'):
        return self.api('POST','/v1/images/generations',json={'model':routes.FAST_MODEL,'prompt':'same prompt','quality':quality,'size':size},headers={'Prefer':'respond-async','X-Idempotency-Key':key})

    def good_fast_download(self,client,url,target,*args):
        Image.new('RGB',(2048,1152),'white').save(target)

    def test_fast_success_settles_once_after_concurrent_recovery(self):
        self.fast_start()
        job=self.api('GET','/api/generation-jobs/by-key/fast-task').json()
        self.assertEqual(job['status'],'reserved',job)
        self.downloader.side_effect=self.good_fast_download
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:self.gateway.execute_generation_job(job['jobId'],None,'test-user',True),range(4)))
        done=self.api('GET','/api/generation-jobs/by-key/fast-task').json()
        self.assertEqual(done['status'],'succeeded',done)
        self.assertEqual(done['creditsCharged'],7)
        self.assertEqual(self.client.post.call_count,1)
        with self.gateway.transaction() as db:
            rows=db.execute('SELECT delta,reason FROM credit_ledger WHERE reference_id=? ORDER BY delta',(job['jobId'],)).fetchall()
            self.assertEqual([(r['delta'],r['reason']) for r in rows],[(-24,'render_reserve'),(17,'render_settlement')])

    def test_pending_billing_refreshes_original_task_without_regeneration(self):
        self.client.get.return_value=delivery_tests.Response(data={'status':'completed','result':{'data':[{'url':'https://example.test/original.png'}]},'billing':{'status':'pending'}})
        self.fast_start()
        job=self.api('GET','/api/generation-jobs/by-key/fast-task').json()
        self.assertTrue(job['canRecover'],job)
        self.downloader.side_effect=self.good_fast_download
        self.client.get.return_value=delivery_tests.Response(data={'status':'completed','result':{'data':[{'url':'https://example.test/original.png'}]},'billing':{'status':'settled','cost_usd':'0.020528'}})
        self.api('POST',f"/api/generation-jobs/{job['jobId']}/recover")
        self.assertEqual(self.api('GET','/api/generation-jobs/by-key/fast-task').json()['creditsCharged'],7)
        self.assertEqual(self.client.post.call_count,1)

    def test_fast_4k_is_rejected_before_any_credit_reservation(self):
        response=self.fast_start(quality='high',size='3840x2160')
        self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(self.client.post.call_count,0)
        with self.gateway.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM render_jobs').fetchone()[0],0)


if __name__=='__main__':unittest.main()
