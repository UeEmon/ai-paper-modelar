"""Project REST endpoints; local single-user API (not Internet-facing)."""
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from urllib.parse import quote

from .projects import (
    AssetCopy, AssetPatch, LibraryProblem, ProjectCreate, ProjectPatch,
    copy_asset, create_project, delete_asset, delete_project, get_asset_file,
    get_project, list_projects, save_asset, update_asset, update_project,
)
from .uploads import MAX_FILE_BYTES

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _problem(exc: LibraryProblem):
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("")
def index():
    return list_projects()


@router.post("", status_code=201)
def create(data: ProjectCreate):
    try:
        return create_project(data)
    except LibraryProblem as exc:
        raise _problem(exc) from exc


@router.get("/{project_id}")
def show(project_id: str):
    try:
        return get_project(project_id)
    except LibraryProblem as exc:
        raise _problem(exc) from exc


@router.patch("/{project_id}")
def edit(project_id: str, data: ProjectPatch):
    try:
        return update_project(project_id, data)
    except LibraryProblem as exc:
        raise _problem(exc) from exc


@router.delete("/{project_id}", status_code=204)
def remove(project_id: str):
    try:
        delete_project(project_id)
    except LibraryProblem as exc:
        raise _problem(exc) from exc
    return Response(status_code=204)


@router.post("/{project_id}/assets", status_code=201)
async def upload(
    project_id: str,
    file: UploadFile = File(...),
    view: str = Form(default="other"),
    notes: str = Form(default=""),
):
    try:
        content = await file.read(MAX_FILE_BYTES + 1)
        return save_asset(project_id, content, file.filename or "", view, notes)
    except LibraryProblem as exc:
        raise _problem(exc) from exc
    finally:
        await file.close()


@router.patch("/{project_id}/assets/{asset_id}")
def edit_asset(project_id: str, asset_id: str, data: AssetPatch):
    try:
        return update_asset(project_id, asset_id, data)
    except LibraryProblem as exc:
        raise _problem(exc) from exc


@router.delete("/{project_id}/assets/{asset_id}", status_code=204)
def remove_asset(project_id: str, asset_id: str):
    try:
        delete_asset(project_id, asset_id)
    except LibraryProblem as exc:
        raise _problem(exc) from exc
    return Response(status_code=204)


@router.post("/{project_id}/assets/{asset_id}/copy", status_code=201)
def reuse_asset(project_id: str, asset_id: str, data: AssetCopy):
    try:
        return copy_asset(project_id, asset_id, data.target_project_id)
    except LibraryProblem as exc:
        raise _problem(exc) from exc


@router.get("/{project_id}/assets/{asset_id}/preview")
def preview(project_id: str, asset_id: str):
    try:
        content, _ = get_asset_file(project_id, asset_id, preview=True)
    except LibraryProblem as exc:
        raise _problem(exc) from exc
    return Response(content, media_type="image/jpeg", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@router.get("/{project_id}/assets/{asset_id}/original")
def original(project_id: str, asset_id: str):
    try:
        content, meta = get_asset_file(project_id, asset_id, preview=False)
    except LibraryProblem as exc:
        raise _problem(exc) from exc
    return Response(content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(meta["name"], safe=""), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
