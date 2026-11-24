"""Local-only OBJ/STL processing session.

No network call or model upload to AI services occurs here. The result is a
bounded in-memory layout expiring one hour after creation.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError

from .retention import save_output
from .generator import ModelSpec, page_jobs, render_pdf, render_svg
from . import mesh_guide
from .mesh_unfolder import MAX_MESH_BYTES, MeshError, load_mesh, parse_mtl, unfold

router = APIRouter(prefix="/api/mesh", tags=["mesh"])

SESSION_TTL = 3600
MAX_JOBS = 8
MAX_MTL_READ = 256 * 1024 + 1
_jobs: dict[str, "MeshJob"] = {}


@dataclass
class MeshJob:
    id: str
    created_at: float
    name: str
    spec: ModelSpec
    parts: list[dict]
    pages: int
    stats: dict
    warnings: list[str]
    # Drawing of the assembly guide, printed as page 1 before the part sheets.
    guide: list[dict] | None = None

    def public(self) -> dict:
        return {
            "id": self.id, "name": self.name,
            "pages": self.pages, "stats": self.stats,
            "warnings": self.warnings, "expires_at": round(self.created_at + SESSION_TTL),
        }


def _prune():
    now = time.time()
    for key, item in list(_jobs.items()):
        if now - item.created_at >= SESSION_TTL:
            _jobs.pop(key,None)


def _job(job_id: str) -> MeshJob:
    _prune()
    if job_id not in _jobs:
        raise HTTPException(404, "展開図が期限切れ、または削除済みです。再アップロードしてください。")
    return _jobs[job_id]


@router.post("/jobs", status_code=201)
async def create_job(
    file: UploadFile = File(...),
    source_unit: str = Form("mm"),
    scale: int = Form(1),
    glue_tabs: bool = Form(True),
    materials: UploadFile | None = File(None),
    use_colors: bool = Form(True),
):
    _prune()
    if len(_jobs) >= MAX_JOBS:
        raise HTTPException(429, "一時ジョブは最大8件です。不要なジョブを削除してください。")
    try:
        data = await file.read(MAX_MESH_BYTES + 1)
    finally:
        await file.close()
    try:
        filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        mesh = load_mesh(data, filename)
        colors = {}
        if materials is not None and materials.filename:
            try:
                raw_mtl = await materials.read(MAX_MTL_READ)
            finally:
                await materials.close()
            colors = parse_mtl(raw_mtl)
        net = unfold(mesh, unit=source_unit, scale=scale, glue_tabs=glue_tabs,
                     materials=colors, use_colors=use_colors)
        spec = ModelSpec(
            name=filename[:80],
            scale=scale, template="box",
            width_m=0.05, depth_m=0.05, height_m=0.05,
            roof="flat", pitch_deg=0,
        )
        sheets = page_jobs(spec, net.parts)
        pages = len(sheets) + 1
        part_pages: dict[int, list[int]] = {}
        for index, sheet in enumerate(sheets, 2):
            for place in sheet["placements"]:
                number = int(place["part"]["name"].split()[-1])
                if index not in part_pages.setdefault(number, []):
                    part_pages[number].append(index)
        guide = mesh_guide.build_page(
            net.guide, name=filename[:80], scale=scale, size_mm=net.stats["size_mm"],
            z_up=mesh.source == "STL", part_pages=part_pages, total_pages=pages)
    except MeshError as exc:
        raise HTTPException(exc.code, str(exc)) from exc
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    job_id = uuid.uuid4().hex
    item = MeshJob(
        job_id, time.time(), filename, spec, net.parts, pages,
        {**net.stats, "scale": scale, "source_unit": source_unit},
        net.warnings, guide,
    )
    _jobs[job_id] = item
    return item.public()


@router.get("/jobs/{job_id}")
def show_job(job_id: str):
    return _job(job_id).public()


@router.get("/jobs/{job_id}/pages/{page}.svg")
def svg(job_id: str, page: int):
    item = _job(job_id)
    if not 0 <= page < item.pages:
        raise HTTPException(404, "該当するページはありません。")
    if page == 0 and item.guide is not None:
        rendered = mesh_guide.to_svg(item.guide)
    else:
        rendered = render_svg(item.spec, page - 1, parts=item.parts, page_offset=1)
    save_output(rendered, "svg")
    return Response(
        rendered,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/jobs/{job_id}/template.pdf")
def pdf(job_id: str):
    item = _job(job_id)
    rendered = render_pdf(item.spec, parts=item.parts, page_offset=1,
                          cover=lambda c: mesh_guide.draw_pdf(c, item.guide))
    save_output(rendered, "pdf")
    return Response(
        rendered,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="mesh-net.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    if _jobs.pop(job_id, None) is None:
        raise HTTPException(404, "指定したジョブは見つかりません。")
    return Response(status_code=204)
