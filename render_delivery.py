"""Private generation progress, scoped upload reuse and resumable original downloads."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

import requests


class DeliveryPending(Exception):
    def __init__(self, run_id: str, message: str):
        super().__init__(message)
        self.run_id = run_id


class RunProgress:
    def __init__(self, directory: Path, run_id: str, on_change=None):
        self.path = directory / f"{run_id}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.on_change = on_change
        self.data = self.read(self.path) or {"runId": run_id, "startedAt": time.time(), "durations": {}}
        self._tick = time.monotonic()

    @staticmethod
    def read(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def update(self, stage: str, **fields):
        now = time.monotonic()
        previous = self.data.get("stage")
        if previous:
            durations = self.data["durations"]
            durations[previous] = round(durations.get(previous, 0) + now - self._tick, 3)
        self._tick = now
        self.data.update(fields, stage=stage, updatedAt=time.time())
        self.data["elapsedSeconds"] = round(self.data["updatedAt"] - self.data["startedAt"], 3)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.path)
        if self.on_change:
            self.on_change(self.data)

    def upload(self, hit: bool, size: int):
        self.update("uploading", uploadedImages=self.data.get("uploadedImages", 0) + (not hit),
                    reusedImages=self.data.get("reusedImages", 0) + hit)


_upload_context = ContextVar("render_upload_context", default=("", None))
_upload_cache: dict[str, tuple[float, str]] = {}
_cache_lock = threading.Lock()
_upload_inflight: dict[str, threading.Event] = {}


@contextmanager
def upload_scope(scope: str, report=None):
    token = _upload_context.set((scope, report))
    try:
        yield
    finally:
        _upload_context.reset(token)


def cached_upload(base: str, key: str, path: Path, mime: str, upload):
    scope, report = _upload_context.get()
    ttl = min(3600, max(0, int(os.getenv("TOAPIS_UPLOAD_CACHE_SECONDS", "3600"))))
    if not scope or not ttl:
        return upload()
    identity = hashlib.sha256((scope + "\0" + base + "\0" + key + "\0" + mime + "\0upload-v1").encode()).digest()
    digest = hashlib.sha256(identity + path.read_bytes()).hexdigest()
    while True:
        with _cache_lock:
            now = time.monotonic()
            entry = _upload_cache.get(digest)
            hit = bool(entry and now - entry[0] < ttl)
            pending = _upload_inflight.get(digest)
            if not hit and pending is None:
                pending = _upload_inflight[digest] = threading.Event()
                owner = True
            else:
                owner = False
        if hit:
            if report:
                report(True, path.stat().st_size)
            return entry[1]
        if owner:
            break
        pending.wait()
    try:
        url = upload()
        with _cache_lock:
            stale = [name for name, entry in _upload_cache.items() if now - entry[0] >= ttl]
            for name in stale:
                _upload_cache.pop(name, None)
            if len(_upload_cache) >= 256:
                _upload_cache.pop(next(iter(_upload_cache)))
            _upload_cache[digest] = (time.monotonic(), url)
    finally:
        with _cache_lock:
            _upload_inflight.pop(digest, None)
            pending.set()
    if report:
        report(False, path.stat().st_size)
    return url


def download_original(client, url: str, target: Path, private_dir: Path, progress=None):
    """Retry only GET; validate Range responses and atomically publish a complete file."""
    private_dir.mkdir(parents=True, exist_ok=True)
    partial = private_dir / (target.name + ".part")
    metadata = private_dir / (target.name + ".json")
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    info = RunProgress.read(metadata)
    if info.get("urlHash") != url_hash:
        partial.unlink(missing_ok=True)
        info = {"urlHash": url_hash}
    last_error = None
    failures_without_progress = 0
    for attempt in range(8):
        before = partial.stat().st_size if partial.exists() else 0
        # Some relays reset after sending the last byte. A complete recorded
        # entity needs validation by the caller, not an unsatisfiable Range GET.
        if before and before == info.get("total"):
            os.replace(partial, target)
            metadata.unlink(missing_ok=True)
            return
        headers = {"Accept-Encoding": "identity"}
        if before:
            headers["Range"] = f"bytes={before}-"
            if info.get("validator"):
                headers["If-Range"] = info["validator"]
        response = None
        try:
            response = client.get(url, headers=headers, stream=True, timeout=(15, 60))
            response.raise_for_status()
            append = False
            if response.status_code == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                if not match or int(match[1]) != before:
                    raise IOError("下载续传范围不一致，已停止拼接")
                total = int(match[3])
                validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
                if info.get("total") not in (None, total) or (info.get("validator") and validator != info["validator"]):
                    partial.unlink(missing_ok=True)
                    info = {"urlHash": url_hash}
                    raise IOError("下载原图已变化，将重新获取完整文件")
                append = before > 0
            else:
                total = int(response.headers.get("Content-Length") or 0)
            info.update(total=total or None, validator=response.headers.get("ETag") or response.headers.get("Last-Modified"))
            metadata.write_text(json.dumps(info), encoding="utf-8")
            with partial.open("ab" if append else "wb") as handle:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        handle.write(chunk)
            if info.get("total") and partial.stat().st_size != info["total"]:
                raise IOError("原图下载不完整")
            if not partial.stat().st_size:
                raise IOError("原图下载为空")
            os.replace(partial, target)
            metadata.unlink(missing_ok=True)
            return
        except (requests.RequestException, OSError, ValueError) as error:
            last_error = error
            after = partial.stat().st_size if partial.exists() else 0
            failures_without_progress = failures_without_progress + 1 if after <= before else 0
            if progress:
                progress.update("downloading", downloadAttempt=attempt + 1, downloadedBytes=after)
            status = getattr(response, "status_code", 0)
            if status in (400, 401, 403, 404, 410) or failures_without_progress >= 3:
                break
            time.sleep(min(2, .5 * (attempt + 1)))
        finally:
            if response is not None:
                response.close()
    raise IOError(f"原图传输中断，已保留原任务，可继续取图：{type(last_error).__name__}") from last_error
