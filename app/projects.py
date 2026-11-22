"""Bounded, expiring RAM-only work sessions. Never persist reference material."""
from __future__ import annotations
import copy
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePath
from pydantic import BaseModel, Field
from .generator import ModelSpec
from .mesh_unfolder import MeshError, load_mesh, thumbnail
from .uploads import EXTENSIONS, MAX_FILE_BYTES, VIEWS, UploadProblem, _prepare_image, _prepare_pdf

_LOCK = threading.RLock()
_UUID = re.compile(r"^[0-9a-f]{32}$")
MAX_PROJECTS = 100
MAX_FILES_PER_PROJECT = 40
MAX_LIBRARY_BYTES = 64 * 1024 * 1024
SESSION_TTL = 900
_projects = {}
_assets = {}
_namespace = None

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


def _id(value: str) -> str:
    if not _UUID.fullmatch(value):
        raise LibraryProblem("IDの形式が不正です。", 404)
    return value


def _name(filename: str) -> str:
    basename = PurePath((filename or "").replace("\\", "/")).name
    if not basename or len(basename) > 240 or re.search(r"[\x00-\x1f\x7f]", basename):
        raise LibraryProblem("ファイル名が不正です。")
    return basename



def _now():
    return datetime.now(timezone.utc).isoformat()


def prune():
    global _namespace
    with _LOCK:
        namespace = os.environ.get("PAPER_MODELAR_DATA_DIR", "/data")
        if namespace != _namespace:
            _projects.clear(); _assets.clear(); _namespace = namespace
        expired = [pid for pid, p in _projects.items() if time.time() - p["_touched"] >= SESSION_TTL]
        for pid in expired:
            _projects.pop(pid, None)
            for aid in [aid for aid, a in _assets.items() if a["project_id"] == pid]:
                _assets.pop(aid, None)


def _project(project_id):
    prune(); _id(project_id)
    if project_id not in _projects: raise LibraryProblem("作業の期限が切れたか、削除されています。", 404)
    p = _projects[project_id]; p["_touched"] = time.time()
    return p


def _asset(project_id, asset_id):
    _project(project_id); _id(asset_id)
    a = _assets.get(asset_id)
    if not a or a["project_id"] != project_id: raise LibraryProblem("この作業内に資料がありません。", 404)
    return a


def _public(item):
    return copy.deepcopy({k: v for k, v in item.items() if not k.startswith("_")})


def list_projects():
    with _LOCK:
        prune()
        return {"projects": [{**_public(p), "asset_count": sum(a["project_id"] == p["id"] for a in _assets.values())}
                             for p in sorted(_projects.values(), key=lambda p: p["updated_at"], reverse=True)]}


def create_project(data: ProjectCreate):
    with _LOCK:
        prune()
        if len(_projects) >= MAX_PROJECTS: raise LibraryProblem("一時作業は100件までです。", 429)
        pid = uuid.uuid4().hex
        p = dict(id=pid, name=data.name.strip(), notes=data.notes,
                 model_spec=(data.model_spec or ModelSpec(name=data.name)).model_dump(),
                 created_at=_now(), updated_at=_now(), _touched=time.time())
        _projects[pid] = p
        return _public(p)


def get_project(project_id):
    with _LOCK:
        return {"project": _public(_project(project_id)),
                "assets": [_public(a) for a in _assets.values() if a["project_id"] == project_id]}


def update_project(project_id, patch: ProjectPatch):
    with _LOCK:
        p = _project(project_id)
        for key, value in patch.model_dump(exclude_unset=True).items():
            if value is not None: p[key] = value.strip() if key == "name" else value
        if not p["name"]: raise LibraryProblem("プロジェクト名を入力してください。")
        p["updated_at"] = _now()
        return _public(p)


def delete_project(project_id):
    with _LOCK:
        _project(project_id); _projects.pop(project_id)
        for aid in [aid for aid, a in _assets.items() if a["project_id"] == project_id]: _assets.pop(aid)


def _capacity(project_id, size):
    if sum(a["project_id"] == project_id for a in _assets.values()) >= MAX_FILES_PER_PROJECT:
        raise LibraryProblem("一時資料は1作業40件までです。", 429)
    if sum(len(a["_original"]) + len(a["_preview"]) for a in _assets.values()) + size > MAX_LIBRARY_BYTES:
        raise LibraryProblem("一時メモリの上限です。不要な資料を削除してください。", 413)


def save_asset(project_id, content, filename, view, notes):
    if not 0 < len(content) <= MAX_FILE_BYTES: raise LibraryProblem("資料は15MB以内にしてください。", 413)
    filename = _name(filename); ext = Path(filename).suffix.lower()
    if ext not in EXTENSIONS | {".obj", ".stl"}: raise LibraryProblem("JPEG・PNG・WebP・PDF・OBJ・STLのみ対応します。", 415)
    if view not in VIEWS or len(notes) > 400: raise LibraryProblem("資料の方向とメモを確認してください。")
    with _LOCK:
        _project(project_id); _capacity(project_id, len(content))
        try:
            if ext in {".obj", ".stl"}: preview, kind, excerpt = thumbnail(load_mesh(content, filename)), "mesh", ""
            elif ext == ".pdf": preview, kind, excerpt = _prepare_pdf(content)
            else: preview, kind = _prepare_image(content); excerpt = ""
        except (UploadProblem, MeshError) as exc:
            raise LibraryProblem(str(exc), getattr(exc, "status_code", getattr(exc, "code", 422))) from exc
        _capacity(project_id, len(content) + len(preview))
        aid = uuid.uuid4().hex; base = "/api/projects/" + project_id + "/assets/" + aid
        a = dict(id=aid, project_id=project_id, name=filename, kind=kind, view=view, notes=notes.strip(),
                 size_bytes=len(content), has_text=bool(excerpt), created_at=_now(),
                 preview_url=base+"/preview", original_url=base+"/original",
                 _original=content, _preview=preview, _excerpt=excerpt)
        _assets[aid] = a
        return _public(a)


def get_asset_file(project_id, asset_id, *, preview=True):
    with _LOCK:
        a = _asset(project_id, asset_id)
        return a["_preview" if preview else "_original"], _public(a)


def update_asset(project_id, asset_id, patch: AssetPatch):
    with _LOCK:
        a = _asset(project_id, asset_id)
        changes = patch.model_dump(exclude_unset=True, exclude_none=True)
        if "view" in changes and changes["view"] not in VIEWS: raise LibraryProblem("資料の方向が不正です。")
        if "name" in changes: changes["name"] = _name(changes["name"])
        a.update(changes)
        return _public(a)


def delete_asset(project_id, asset_id):
    with _LOCK:
        _asset(project_id, asset_id); _assets.pop(asset_id)


def copy_asset(project_id, asset_id, destination_id):
    with _LOCK:
        a = _asset(project_id, asset_id)
        return save_asset(destination_id, a["_original"], a["name"], a["view"], a["notes"])


def get_asset_for_ai(project_id, asset_id):
    from .uploads import Asset
    with _LOCK:
        a = _asset(project_id, asset_id)
        if a["kind"] == "mesh": raise LibraryProblem("OBJ/STL原本は画像AI参照として送信できません。", 422)
        return Asset(id=a["id"], name=a["name"], kind=a["kind"], view=a["view"], notes=a["notes"],
                     uploaded_bytes=a["size_bytes"], preview=a["_preview"], excerpt=a["_excerpt"])
