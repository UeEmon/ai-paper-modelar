"""Local, persistent project library for photos, plans and model settings.

SQLite indexes project and file metadata; originals and EXIF-free previews are
stored in a Docker volume. Local single-user deployment ONLY (no authentication).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePath
from typing import Any

from pydantic import BaseModel, Field

from .generator import ModelSpec
from .mesh_unfolder import MeshError, load_mesh, thumbnail
from .uploads import (
    EXTENSIONS, MAX_FILE_BYTES, VIEWS, UploadProblem,
    _prepare_image, _prepare_pdf,
)

_LOCK = threading.RLock()
_UUID = re.compile(r"^[0-9a-f]{32}$")
MAX_PROJECTS = 100
MAX_FILES_PER_PROJECT = 40
MAX_LIBRARY_BYTES = 1024 * 1024 * 1024


class LibraryProblem(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=1000)
    model_spec: ModelSpec | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)
    model_spec: ModelSpec | None = None


class AssetPatch(BaseModel):
    view: str | None = None
    notes: str | None = Field(default=None, max_length=400)
    name: str | None = Field(default=None, min_length=1, max_length=120)


class AssetCopy(BaseModel):
    target_project_id: str


def _root() -> Path:
    root = Path(os.environ.get("PAPER_MODELAR_DATA_DIR", "/data")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _id(value: str) -> str:
    if not _UUID.fullmatch(value):
        raise LibraryProblem("IDの形式が不正です。", 404)
    return value


def _name(filename: str) -> str:
    basename = PurePath((filename or "").replace("\\", "/")).name
    if not basename or len(basename) > 240 or re.search(r"[\x00-\x1f\x7f]", basename):
        raise LibraryProblem("ファイル名が不正です。")
    return basename


@contextmanager
def _db():
    conn = sqlite3.connect(str(_root() / "library.sqlite3"), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                spec_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE TABLE IF NOT EXISTS project_assets (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                view TEXT NOT NULL,
                notes TEXT NOT NULL,
                bytes INTEGER NOT NULL,
                stored_name TEXT NOT NULL,
                text_excerpt TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE INDEX IF NOT EXISTS ix_asset_project ON project_assets(project_id);
        """)
        with conn:
            yield conn
    finally:
        conn.close()


def _project_row(conn, project_id: str):
    item = conn.execute("SELECT * FROM projects WHERE id=?", (_id(project_id),)).fetchone()
    if item is None:
        raise LibraryProblem("プロジェクトが見つかりません。", 404)
    return item


def _asset_row(conn, project_id: str, asset_id: str):
    _project_row(conn, project_id)
    row = conn.execute(
        "SELECT * FROM project_assets WHERE project_id=? AND id=?",
        (project_id, _id(asset_id)),
    ).fetchone()
    if row is None:
        raise LibraryProblem("指定したプロジェクト内に資料がありません。", 404)
    return row


def _project_json(row) -> dict[str, Any]:
    return {
        "id": row["id"], "name": row["name"], "notes": row["notes"],
        "model_spec": json.loads(row["spec_json"]),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _asset_json(row) -> dict[str, Any]:
    base = "/api/projects/" + row["project_id"] + "/assets/" + row["id"]
    return {
        "id": row["id"], "project_id": row["project_id"], "name": row["name"],
        "kind": row["kind"], "view": row["view"], "notes": row["notes"],
        "size_bytes": row["bytes"], "has_text": bool(row["text_excerpt"]),
        "created_at": row["created_at"],
        "preview_url": base + "/preview",
        "original_url": base + "/original",
    }


def list_projects():
    with _LOCK, _db() as conn:
        rows = conn.execute("""
          SELECT p.*, COUNT(a.id) AS asset_count
          FROM projects p LEFT JOIN project_assets a ON a.project_id=p.id
          GROUP BY p.id ORDER BY p.updated_at DESC, p.id DESC
        """).fetchall()
        return {"projects": [{**_project_json(row), "asset_count": row["asset_count"]}
                             for row in rows]}


def create_project(data: ProjectCreate):
    with _LOCK, _db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        if count >= MAX_PROJECTS:
            raise LibraryProblem("プロジェクトの上限は100件です。", 429)
        project_id = uuid.uuid4().hex
        spec = data.model_spec or ModelSpec(name=data.name)
        conn.execute(
            "INSERT INTO projects(id,name,notes,spec_json) VALUES(?,?,?,?)",
            (project_id, data.name.strip(), data.notes, spec.model_dump_json()),
        )
        row = _project_row(conn, project_id)
        return _project_json(row)


def get_project(project_id: str):
    with _LOCK, _db() as conn:
        project = _project_json(_project_row(conn, project_id))
        rows = conn.execute(
            "SELECT * FROM project_assets WHERE project_id=? ORDER BY created_at, id",
            (project_id,),
        ).fetchall()
        return {"project": project, "assets": [_asset_json(row) for row in rows]}


def update_project(project_id: str, patch: ProjectPatch):
    with _LOCK, _db() as conn:
        row = _project_row(conn, project_id)
        changes = patch.model_fields_set
        name = patch.name.strip() if "name" in changes and patch.name is not None else row["name"]
        if not name:
            raise LibraryProblem("プロジェクト名を入力してください。")
        notes = patch.notes if "notes" in changes and patch.notes is not None else row["notes"]
        spec = patch.model_spec.model_dump_json() if patch.model_spec is not None else row["spec_json"]
        conn.execute("""
            UPDATE projects SET name=?,notes=?,spec_json=?,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?
        """, (name, notes, spec, project_id))
        return _project_json(_project_row(conn, project_id))


def delete_project(project_id: str):
    with _LOCK, _db() as conn:
        _project_row(conn, project_id)
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        # Only a validated UUID under the configured data root is deleted.
        shutil.rmtree(_root() / "projects" / project_id, ignore_errors=True)


def _asset_path(project_id: str, stored_name: str) -> Path:
    # Stored names were generated internally; always reject non-generated names.
    if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|png|webp|pdf|jpeg|obj|stl)", stored_name):
        raise LibraryProblem("保存ファイルの識別情報が不正です。", 500)
    return _root() / "projects" / _id(project_id) / "files" / stored_name


def _preview_path(project_id: str, asset_id: str) -> Path:
    return _root() / "projects" / _id(project_id) / "previews" / (_id(asset_id) + ".jpg")


def _atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".part-", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _check_capacity(conn, project_id: str, added_bytes: int):
    count = conn.execute(
        "SELECT COUNT(*) FROM project_assets WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    if count >= MAX_FILES_PER_PROJECT:
        raise LibraryProblem("1プロジェクトに保存できる資料は40件までです。", 429)
    used = conn.execute("SELECT COALESCE(SUM(bytes),0) FROM project_assets").fetchone()[0]
    if used + added_bytes > MAX_LIBRARY_BYTES:
        raise LibraryProblem("資料保存容量の上限（原本合計1GB）です。", 413)


def save_asset(project_id: str, content: bytes, filename: str, view: str, notes: str):
    if not 0 < len(content) <= MAX_FILE_BYTES:
        raise LibraryProblem("資料サイズは1件15MB以内にしてください。", 413)
    filename = _name(filename)
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in EXTENSIONS | {".obj", ".stl"}:
        raise LibraryProblem("JPEG・PNG・WebP・PDF・OBJ・STLのみ対応します。", 415)
    if view not in VIEWS:
        raise LibraryProblem("資料の方向を選択してください。")
    notes = (notes or "").strip()
    if len(notes) > 400:
        raise LibraryProblem("メモは400文字以内です。")
    try:
        if ext in {".obj", ".stl"}:
            mesh = load_mesh(content, filename)
            preview, kind, excerpt = thumbnail(mesh), "mesh", ""
        elif ext == ".pdf":
            preview, kind, excerpt = _prepare_pdf(content)
        else:
            preview, kind = _prepare_image(content)
            excerpt = ""
    except UploadProblem as exc:
        raise LibraryProblem(str(exc), exc.status_code) from exc
    except MeshError as exc:
        raise LibraryProblem(str(exc), exc.code) from exc

    with _LOCK, _db() as conn:
        _project_row(conn, project_id)
        _check_capacity(conn, project_id, len(content))
        asset_id = uuid.uuid4().hex
        filename_on_disk = asset_id + ext
        original_path = _asset_path(project_id, filename_on_disk)
        preview_path = _preview_path(project_id, asset_id)
        try:
            _atomic_write(original_path, content)
            _atomic_write(preview_path, preview)
            conn.execute("""
                INSERT INTO project_assets(
                    id,project_id,name,kind,view,notes,bytes,stored_name,text_excerpt
                ) VALUES(?,?,?,?,?,?,?,?,?)
            """, (asset_id, project_id, filename, kind, view, notes,
                  len(content), filename_on_disk, excerpt))
            conn.execute(
                "UPDATE projects SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (project_id,),
            )
        except Exception:
            original_path.unlink(missing_ok=True)
            preview_path.unlink(missing_ok=True)
            raise
        row = _asset_row(conn, project_id, asset_id)
        return _asset_json(row)


def get_asset_file(project_id: str, asset_id: str, *, preview: bool = True):
    with _LOCK, _db() as conn:
        row = _asset_row(conn, project_id, asset_id)
        path = (_preview_path(project_id, asset_id) if preview
                else _asset_path(project_id, row["stored_name"]))
        if not path.is_file():
            raise LibraryProblem("保存した資料が見つかりません。", 404)
        return path, _asset_json(row)


def update_asset(project_id: str, asset_id: str, patch: AssetPatch):
    with _LOCK, _db() as conn:
        row = _asset_row(conn, project_id, asset_id)
        changes = patch.model_fields_set
        view = patch.view if "view" in changes and patch.view is not None else row["view"]
        if view not in VIEWS:
            raise LibraryProblem("資料の方向が不正です。")
        notes = patch.notes if "notes" in changes and patch.notes is not None else row["notes"]
        name = _name(patch.name) if "name" in changes and patch.name is not None else row["name"]
        conn.execute(
            "UPDATE project_assets SET name=?,view=?,notes=? WHERE id=?",
            (name, view, notes, asset_id),
        )
        conn.execute(
            "UPDATE projects SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (project_id,),
        )
        return _asset_json(_asset_row(conn, project_id, asset_id))


def delete_asset(project_id: str, asset_id: str):
    with _LOCK, _db() as conn:
        row = _asset_row(conn, project_id, asset_id)
        original = _asset_path(project_id, row["stored_name"])
        preview = _preview_path(project_id, asset_id)
        conn.execute(
            "DELETE FROM project_assets WHERE id=? AND project_id=?", (asset_id, project_id)
        )
        conn.execute(
            "UPDATE projects SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (project_id,),
        )
        original.unlink(missing_ok=True)
        preview.unlink(missing_ok=True)


def copy_asset(project_id: str, asset_id: str, destination_id: str):
    with _LOCK, _db() as conn:
        source = _asset_row(conn, project_id, asset_id)
        _project_row(conn, destination_id)
        _check_capacity(conn, destination_id, source["bytes"])
        new_id = uuid.uuid4().hex
        ext = Path(source["stored_name"]).suffix
        new_stored = new_id + ext
        target = _asset_path(destination_id, new_stored)
        target_preview = _preview_path(destination_id, new_id)
        try:
            original_path = _asset_path(project_id, source["stored_name"])
            if not original_path.is_file():
                raise LibraryProblem("複製元ファイルがありません。", 404)
            _atomic_write(target, original_path.read_bytes())
            _atomic_write(target_preview, _preview_path(project_id, asset_id).read_bytes())
            conn.execute("""
                INSERT INTO project_assets(
                    id,project_id,name,kind,view,notes,bytes,stored_name,text_excerpt
                ) VALUES(?,?,?,?,?,?,?,?,?)
            """, (new_id, destination_id, source["name"], source["kind"],
                  source["view"], source["notes"], source["bytes"], new_stored,
                  source["text_excerpt"]))
            conn.execute(
                "UPDATE projects SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (destination_id,),
            )
        except Exception:
            target.unlink(missing_ok=True)
            target_preview.unlink(missing_ok=True)
            raise
        return _asset_json(_asset_row(conn, destination_id, new_id))


def get_asset_for_ai(project_id: str, asset_id: str):
    """Return a small compatible Asset; never pass the raw original to AI."""
    from .uploads import Asset
    with _LOCK, _db() as conn:
        row = _asset_row(conn, project_id, asset_id)
        if row["kind"] == "mesh":
            raise LibraryProblem("OBJ/STL原本は画像AI参照として送信できません。メッシュ展開画面を使用してください。", 422)
        path = _preview_path(project_id, asset_id)
        if not path.is_file():
            raise LibraryProblem("資料画像が見つかりません。", 404)
        return Asset(
            id=row["id"], name=row["name"], kind=row["kind"],
            view=row["view"], notes=row["notes"],
            uploaded_bytes=row["bytes"], preview=path.read_bytes(),
            excerpt=row["text_excerpt"],
        )
