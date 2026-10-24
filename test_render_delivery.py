"""Delivery recovery tests: no paid API calls, isolated files and billing database."""
import asyncio
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import requests
from PIL import Image

import render_delivery as delivery
import test_generation_rate_limit as rate_tests


class Response:
    def __init__(self, body=b"", status=200, headers=None, data=None, broken=False):
        self.body, self.status_code, self.headers, self.data, self.broken = body, status, headers or {}, data, broken

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)

    def json(self):
        return self.data

    def iter_content(self, chunk_size):
        yield self.body
        if self.broken:
            raise requests.exceptions.ChunkedEncodingError("interrupted")

    def close(self):
        pass


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.target = self.root / "original.png"
        self.private = self.root / "private"
        self.enterContext(patch.object(delivery.time, "sleep"))

    def test_interrupted_download_resumes_with_verified_range(self):
        client = Mock()
        client.get.side_effect = [Response(b"abc", headers={"Content-Length": "6", "ETag": '"v1"'}, broken=True),
                                  Response(b"def", 206, {"Content-Range": "bytes 3-5/6", "ETag": '"v1"'})]
        delivery.download_original(client, "https://example.test/image", self.target, self.private)
        self.assertEqual(self.target.read_bytes(), b"abcdef")
        self.assertEqual(client.get.call_args.kwargs["headers"]["Range"], "bytes=3-")
        self.assertEqual(client.get.call_args.kwargs["headers"]["If-Range"], '"v1"')
        self.assertEqual(client.post.call_count, 0)

    def test_server_ignoring_range_restarts_without_duplicate_bytes(self):
        client = Mock()
        client.get.side_effect = [Response(b"abc", headers={"Content-Length": "6"}, broken=True),
                                  Response(b"abcdef", headers={"Content-Length": "6"})]
        delivery.download_original(client, "https://example.test/image", self.target, self.private)
        self.assertEqual(self.target.read_bytes(), b"abcdef")

    def test_connection_reset_after_last_byte_does_not_request_unsatisfiable_range(self):
        client = Mock()
        client.get.return_value = Response(b"abcdef", headers={"Content-Length": "6", "ETag": '"v1"'}, broken=True)
        delivery.download_original(client, "https://example.test/image", self.target, self.private)
        self.assertEqual(self.target.read_bytes(), b"abcdef")
        self.assertEqual(client.get.call_count, 1)

    def test_pending_partial_survives_and_recovery_only_downloads_remaining_bytes(self):
        client = Mock()
        client.get.side_effect = [Response(b"abc", headers={"Content-Length": "6", "ETag": '"v1"'}, broken=True)] + [requests.ConnectionError("offline")] * 3
        with self.assertRaises(OSError):
            delivery.download_original(client, "https://example.test/image", self.target, self.private)
        self.assertFalse(self.target.exists())
        client.get.side_effect = [Response(b"def", 206, {"Content-Range": "bytes 3-5/6", "ETag": '"v1"'})]
        delivery.download_original(client, "https://example.test/image", self.target, self.private)
        self.assertEqual(self.target.read_bytes(), b"abcdef")

    def test_changed_object_is_not_spliced_into_old_partial(self):
        client = Mock()
        client.get.side_effect = [Response(b"abc", headers={"Content-Length": "6", "ETag": '"v1"'}, broken=True),
                                  Response(b"XYZ", 206, {"Content-Range": "bytes 3-5/6", "ETag": '"v2"'}),
                                  Response(b"UVWXYZ", headers={"Content-Length": "6", "ETag": '"v2"'})]
        delivery.download_original(client, "https://example.test/image", self.target, self.private)
        self.assertEqual(self.target.read_bytes(), b"UVWXYZ")

    def test_upload_cache_isolated_by_user_key_base_mime_and_bytes(self):
        path = self.root / "input.png"
        path.write_bytes(b"image-one")
        upload = Mock(side_effect=lambda: f"https://example.test/{upload.call_count}")
        with patch.dict(delivery._upload_cache, {}, clear=True):
            def send(scope="user-a", key="key-a", base="https://base-a", mime="image/png"):
                with delivery.upload_scope(scope):
                    return delivery.cached_upload(base, key, path, mime, upload)
            first = send()
            self.assertEqual(send(), first)
            self.assertNotEqual(send(scope="user-b"), first)
            self.assertNotEqual(send(key="key-b"), first)
            self.assertNotEqual(send(base="https://base-b"), first)
            self.assertNotEqual(send(mime="image/jpeg"), first)
            path.write_bytes(b"image-two")
            self.assertNotEqual(send(), first)
            self.assertEqual(upload.call_count, 6)

    def test_upload_reuse_expires_after_one_hour(self):
        path = self.root / "input.png"
        path.write_bytes(b"image")
        upload = Mock(side_effect=["first-url", "fresh-url"])
        with patch.dict(delivery._upload_cache, {}, clear=True), patch.object(delivery.time, "monotonic", return_value=100) as clock:
            with delivery.upload_scope("user"):
                self.assertEqual(delivery.cached_upload("base", "key", path, "image/png", upload), "first-url")
                clock.return_value = 3699
                self.assertEqual(delivery.cached_upload("base", "key", path, "image/png", upload), "first-url")
                clock.return_value = 3700
                self.assertEqual(delivery.cached_upload("base", "key", path, "image/png", upload), "fresh-url")

    def test_parallel_requests_upload_identical_reference_only_once(self):
        import threading
        path = self.root / "input.png"
        path.write_bytes(b"parallel-image")
        def upload_once():
            threading.Event().wait(.05)
            return "original-url"
        upload = Mock(side_effect=upload_once)
        def send(_):
            with delivery.upload_scope("same-user"):
                return delivery.cached_upload("base", "key", path, "image/png", upload)
        with patch.dict(delivery._upload_cache, {}, clear=True), ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(send, range(4))), ["original-url"] * 4)
        self.assertEqual(upload.call_count, 1)


class DeliveryJobTests(rate_tests.GenerationRateLimitTests):
    def setUp(self):
        super().setUp()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.core = self.gateway.render_core
        self.enterContext(patch.object(self.core, "RUN_DIR", self.root / "runs"))
        self.enterContext(patch.object(self.core, "JOB_STATE_DIR", self.root / "state"))
        self.enterContext(patch.object(self.core, "DATA_DIR", self.root / "data"))
        self.enterContext(patch.object(self.core, "current_api_key", return_value="test-key"))
        self.enterContext(patch.object(self.core, "_env_key", return_value="test-key"))
        self.enterContext(patch.object(self.core, "current_base_url", return_value="https://example.test"))
        self.enterContext(patch.object(self.core.time, "sleep"))
        self.client = Mock()
        self.client.post.return_value = Response(data={"id": "upstream-original"})
        self.client.get.return_value = Response(data={"status": "completed", "result": {"data": [{"url": "https://example.test/original.png"}]}})
        self.enterContext(patch.object(self.core, "toapis_http_client", return_value=self.client))
        self.downloader = self.enterContext(patch.object(delivery, "download_original", side_effect=OSError("interrupted")))

    def api(self, method, path, **kwargs):
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.gateway.app), base_url="http://test") as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(send())

    def start(self, key="delivery-task"):
        return self.api("POST", "/v1/images/generations", json={"model": "gpt-image-2.5", "prompt": "test", "quality": "low", "size": "1024x1024"}, headers={"Prefer": "respond-async", "X-Idempotency-Key": key})

    def good_download(self, client, url, target, *args):
        Image.new("RGB", (1024, 1024), "white").save(target)

    def test_download_failure_keeps_reservation_then_recovers_once(self):
        response = self.start()
        self.assertEqual(response.status_code, 202, response.text)
        job = self.api("GET", "/api/generation-jobs/by-key/delivery-task").json()
        self.assertTrue(job["canRecover"], job)
        self.assertEqual(job["status"], "reserved")
        self.assertNotIn("upstream-original", json.dumps(job))
        self.downloader.side_effect = self.good_download
        path = f"/api/generation-jobs/{job['jobId']}/recover"
        self.assertEqual(self.api("POST", path).status_code, 200)
        completed = self.api("GET", "/api/generation-jobs/by-key/delivery-task").json()
        self.assertEqual(completed["status"], "succeeded")
        self.assertTrue(completed["data"][0]["url"].startswith("/data/runs/"))
        self.assertEqual(self.api("POST", path).status_code, 200)
        self.assertEqual(self.start().status_code, 202)
        self.assertEqual(self.client.post.call_count, 1)
        with self.gateway.transaction() as db:
            ledger = db.execute("SELECT reason,delta FROM credit_ledger WHERE reference_id=?", (job["jobId"],)).fetchall()
            self.assertEqual([(row["reason"], row["delta"]) for row in ledger], [("render_reserve", -5)])

    def test_other_account_cannot_read_or_recover(self):
        job = self.start().json()
        self.gateway.app.dependency_overrides[self.gateway.current_user] = lambda: {"id": "other-user"}
        self.assertEqual(self.api("GET", "/api/generation-jobs/by-key/delivery-task").status_code, 404)
        self.assertEqual(self.api("GET", f"/api/generation-jobs/{job['jobId']}").status_code, 404)
        self.assertEqual(self.api("POST", f"/api/generation-jobs/{job['jobId']}/recover").status_code, 404)
        self.assertEqual(self.api("GET", "/api/generation-jobs").json(), {"items": []})

    def test_poll_connection_failure_recovers_same_upstream_task(self):
        self.client.get.side_effect = requests.ConnectionError("poll interrupted")
        self.start()
        job = self.api("GET", "/api/generation-jobs/by-key/delivery-task").json()
        self.assertTrue(job["canRecover"])
        self.client.get.side_effect = None
        self.downloader.side_effect = self.good_download
        self.api("POST", f"/api/generation-jobs/{job['jobId']}/recover")
        self.assertEqual(self.client.post.call_count, 1)
        self.assertEqual(self.api("GET", "/api/generation-jobs/by-key/delivery-task").json()["status"], "succeeded")

    def test_concurrent_recovery_is_serialized_and_not_charged_again(self):
        self.start()
        job = self.api("GET", "/api/generation-jobs/by-key/delivery-task").json()
        self.downloader.side_effect = self.good_download
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.gateway.execute_generation_job(job["jobId"], None, "test-user", True), range(4)))
        self.assertEqual(self.client.post.call_count, 1)
        self.assertEqual(self.downloader.call_count, 2)
        with self.gateway.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM credit_ledger WHERE reference_id=?", (job["jobId"],)).fetchone()[0], 1)

    def test_interrupted_worker_with_saved_task_remains_recoverable(self):
        self.start()
        job = self.api("GET", "/api/generation-jobs/by-key/delivery-task").json()
        with self.gateway.transaction() as db:
            run_id = db.execute("SELECT run_id FROM render_jobs WHERE id=?", (job["jobId"],)).fetchone()[0]
        tracker = delivery.RunProgress(self.core.JOB_STATE_DIR, run_id)
        tracker.update("downloading")
        self.assertTrue(self.api("GET", "/api/generation-jobs/by-key/delivery-task").json()["canRecover"])


if __name__ == "__main__":
    unittest.main()
