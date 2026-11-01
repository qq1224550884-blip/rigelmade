"""Private snapshots, complete media and concurrent-save protection; no paid API."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import asyncio
import httpx

from fastapi import FastAPI, Header, HTTPException

from canvas_service import build_canvas_router


def snapshot(pid="canvas-a", media=b"original-image-bytes", **project):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("projects.json", json.dumps({"app": "infinite-canvas", "version": 3, "projects": [{
            "project": {"id": pid, "title": "QA canvas", "nodes": [{"id": "img", "metadata": {"storageKey": "image:qa"}}], **project},
            "files": [{"storageKey": "image:qa", "path": "files/image.png", "bytes": len(media), "mimeType": "image/png"}],
        }]}))
        archive.writestr("files/image.png", media)
    return stream.getvalue()


class CanvasTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        app = FastAPI()
        def auth(authorization: str = Header("")):
            if authorization not in {"Bearer alice", "Bearer bob"}:
                raise HTTPException(401)
            return {"id": authorization[7:]}
        app.include_router(build_canvas_router(auth, Path(self.temp)))
        self.app = app

    def request(self, method, path, **kwargs):
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(send())

    def save(self, raw=None, user="alice", revision=0):
        return self.request("PUT", "/api/canvas/projects/canvas-a", headers={"Authorization": "Bearer " + user},
                               data={"revision": revision}, files={"snapshot": ("canvas.zip", raw or snapshot(), "application/zip")})

    def test_private_roundtrip_includes_original_bytes(self):
        raw = snapshot()
        saved = self.save(raw)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["revision"], 1)
        response = self.request("GET", "/api/canvas/projects/canvas-a", headers={"Authorization": "Bearer alice"})
        self.assertEqual(response.content, raw)
        self.assertEqual(response.headers["x-canvas-revision"], "1")
        self.assertEqual(self.request("GET", "/api/canvas/projects/canvas-a").status_code, 401)
        self.assertEqual(self.request("GET", "/api/canvas/projects/canvas-a", headers={"Authorization": "Bearer bob"}).status_code, 404)
        self.assertEqual(self.request("GET", "/api/canvas/projects", headers={"Authorization": "Bearer bob"}).json()["items"], [])

    def test_stale_device_cannot_overwrite_or_delete(self):
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(self.save(revision=1).json()["revision"], 2)
        self.assertEqual(self.save(revision=1).status_code, 409)
        self.assertEqual(self.request("DELETE", "/api/canvas/projects/canvas-a?revision=1", headers={"Authorization": "Bearer alice"}).status_code, 409)
        self.assertEqual(self.request("DELETE", "/api/canvas/projects/canvas-a?revision=2", headers={"Authorization": "Bearer bob"}).status_code, 404)
        self.assertEqual(self.request("DELETE", "/api/canvas/projects/canvas-a?revision=2", headers={"Authorization": "Bearer alice"}).status_code, 200)

    def test_malformed_and_incomplete_snapshots_leave_previous_version(self):
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(self.save(b"not a zip", revision=1).status_code, 400)
        self.assertEqual(self.save(snapshot(pid="wrong"), revision=1).status_code, 400)
        broken = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(snapshot())) as source, zipfile.ZipFile(broken, "w") as target:
            target.writestr("projects.json", source.read("projects.json"))
        self.assertEqual(self.save(broken.getvalue(), revision=1).status_code, 400)
        response = self.request("GET", "/api/canvas/projects", headers={"Authorization": "Bearer alice"})
        self.assertEqual(response.json()["items"][0]["revision"], 1)

    def test_same_local_id_is_scoped_to_account(self):
        self.assertEqual(self.save(user="alice").status_code, 200)
        self.assertEqual(self.save(user="bob").status_code, 200)
        self.assertEqual(len(list(Path(self.temp).glob("*/*.zip"))), 2)

    def test_missing_material_reference_is_rejected(self):
        raw = snapshot(nodes=[{"id": "result", "metadata": {"storageKey": "image:qa", "references": ["image:missing-material"]}}])
        self.assertEqual(self.save(raw).status_code, 400)


if __name__ == "__main__":
    unittest.main()
