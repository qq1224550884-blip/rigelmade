"""Account-private, revision-checked canvas snapshots including original media."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import time
import uuid
import zipfile
from contextlib import closing

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
ACCOUNT_QUOTA = 512 * 1024 * 1024


def validate_snapshot(raw: bytes, project_id: str):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > 2000 or sum(i.file_size for i in infos) > MAX_EXPANDED:
                raise ValueError("画布资源过多，请拆分项目后保存。")
            if len({i.filename for i in infos}) != len(infos):
                raise ValueError("压缩包包含重复文件。")
            for info in infos:
                path = PurePosixPath(info.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                    raise ValueError("画布文件路径无效。")
            manifest_info = archive.getinfo("projects.json")
            if manifest_info.file_size > 8 * 1024 * 1024:
                raise ValueError("画布文档过大，请拆分项目。")
            manifest = json.loads(archive.read(manifest_info))
            if manifest.get("app") != "infinite-canvas" or manifest.get("version") != 3 or len(manifest.get("projects", [])) != 1:
                raise ValueError("请选择包含一个画布的完整项目文件。")
            entry = manifest["projects"][0]
            project = entry["project"]
            if project.get("id") != project_id or not isinstance(project.get("nodes"), list):
                raise ValueError("画布编号或节点数据无效。")
            for media in entry["files"]:
                if archive.getinfo(media["path"]).file_size != media["bytes"]:
                    raise ValueError("画布原图不完整，未保存。")
            declared = {media["storageKey"] for media in entry["files"]}
            def check_resources(value):
                if isinstance(value, str) and re.match(r"^(image|video|audio|file):", value) and value not in declared:
                    raise ValueError("画布缺少引用原图，未保存。")
                if isinstance(value, dict):
                    for child in value.values():
                        check_resources(child)
                elif isinstance(value, list):
                    for child in value:
                        check_resources(child)
            check_resources(project)
            if archive.testzip() is not None:
                raise ValueError("画布资源校验失败。")
            return str(project.get("title") or "未命名画布")[:200], len(project["nodes"])
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise HTTPException(400, str(exc) if isinstance(exc, ValueError) else "画布文件损坏或缺少资源。") from exc


def build_canvas_router(auth, root: Path):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    database = root / "canvas.sqlite3"

    def connect():
        connection = sqlite3.connect(database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    with closing(connect()) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS projects (
            owner TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL,
            revision INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            bytes INTEGER NOT NULL, node_count INTEGER NOT NULL, file TEXT NOT NULL,
            PRIMARY KEY(owner,id))""")
        connection.commit()
    router = APIRouter(prefix="/api/canvas", tags=["canvas"])

    def check_id(pid):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", pid):
            raise HTTPException(400, "画布编号无效。")

    def summary(row):
        return {"id": row["id"], "title": row["title"], "revision": row["revision"],
                "updatedAt": row["updated_at"], "bytes": row["bytes"], "nodeCount": row["node_count"]}

    @router.get("/projects")
    def list_projects(user=Depends(auth)):
        with closing(connect()) as connection:
            rows = connection.execute("SELECT * FROM projects WHERE owner=? ORDER BY updated_at DESC", (user["id"],)).fetchall()
        return {"items": [summary(row) for row in rows], "maxArchiveBytes": MAX_ARCHIVE}

    @router.get("/projects/{pid}")
    def download(pid: str, user=Depends(auth)):
        check_id(pid)
        with closing(connect()) as connection:
            row = connection.execute("SELECT * FROM projects WHERE owner=? AND id=?", (user["id"], pid)).fetchone()
        if not row or not (root / row["file"]).is_file():
            raise HTTPException(404, "账号中没有这个画布。")
        return FileResponse(root / row["file"], media_type="application/zip", filename="canvas.zip",
                            headers={"X-Canvas-Revision": str(row["revision"]), "Cache-Control": "private, no-store"})

    @router.put("/projects/{pid}")
    async def save(pid: str, revision: int = Form(0), snapshot: UploadFile = File(...), user=Depends(auth)):
        check_id(pid)
        raw = await snapshot.read(MAX_ARCHIVE + 1)
        if len(raw) > MAX_ARCHIVE:
            raise HTTPException(413, "单个画布最多 64MB，请拆分项目或导出到本机。")
        title, count = await run_in_threadpool(validate_snapshot, raw, pid)
        owner_dir = hashlib.sha256(user["id"].encode()).hexdigest()
        relative = f"{owner_dir}/{uuid.uuid4().hex}.zip"
        destination = root / relative
        destination.parent.mkdir(exist_ok=True)
        old_file = None
        connection = connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute("SELECT * FROM projects WHERE owner=? AND id=?", (user["id"], pid)).fetchone()
            if (old["revision"] if old else 0) != revision:
                raise HTTPException(409, "另一台设备已保存新版本。请从账号打开最新副本，或将当前画布另存为新项目。")
            total = connection.execute("SELECT COALESCE(SUM(bytes),0) FROM projects WHERE owner=?", (user["id"],)).fetchone()[0]
            if total - (old["bytes"] if old else 0) + len(raw) > ACCOUNT_QUOTA:
                raise HTTPException(413, "账号画布存储已达到 512MB，请先导出并整理旧画布。")
            destination.write_bytes(raw)
            updated = int(time.time() * 1000)
            connection.execute("INSERT OR REPLACE INTO projects VALUES(?,?,?,?,?,?,?,?)",
                               (user["id"], pid, title, revision + 1, updated, len(raw), count, relative))
            # Explicit columns keep the archive and revision in one committed snapshot.
            connection.commit()
            old_file = old["file"] if old else None
        except Exception:
            connection.rollback()
            destination.unlink(missing_ok=True)
            raise
        finally:
            connection.close()
        if old_file:
            (root / old_file).unlink(missing_ok=True)
        return {"id": pid, "title": title, "revision": revision + 1, "updatedAt": updated, "bytes": len(raw), "nodeCount": count}

    @router.delete("/projects/{pid}")
    def delete(pid: str, revision: int, user=Depends(auth)):
        check_id(pid)
        with closing(connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM projects WHERE owner=? AND id=?", (user["id"], pid)).fetchone()
            if not row:
                raise HTTPException(404, "账号中没有这个画布。")
            if row["revision"] != revision:
                raise HTTPException(409, "云端版本已更新，请刷新列表再删除。")
            connection.execute("DELETE FROM projects WHERE owner=? AND id=?", (user["id"], pid))
            connection.commit()
        (root / row["file"]).unlink(missing_ok=True)
        return {"ok": True}

    return router
