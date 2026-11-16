"""HTTP entrypoint for AI Paper Modelar."""
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, File, Form, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .ai import ProposalRequest, proposals
from .generator import ModelSpec, render_pdf, render_svg, summary
from .research import research
from .uploads import add_asset, get_asset, delete_asset, UploadProblem, MAX_FILE_BYTES

HERE = Path(__file__).resolve().parent
app = FastAPI(title="AI Paper Modelar", version="0.1.0")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

@app.get("/", include_in_schema=False)
def homepage():
    return FileResponse(HERE / "static" / "index.html")

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/research")
async def find(q: str = Query(min_length=2, max_length=120)):
    try:
        return await research(q)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="公開資料を取得できませんでした") from exc

@app.post("/api/proposals")
async def plan(req: ProposalRequest):
    try:
        return await proposals(req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc

@app.post("/api/model")
def calculate(req: ModelSpec):
    try:
        return summary(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.post("/api/template.svg")
def svg(req: ModelSpec, page: int = Query(default=0, ge=0)):
    try:
        rendered = render_svg(req, page)
    except (IndexError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(rendered, media_type="image/svg+xml")

@app.post("/api/template.pdf")
def pdf(req: ModelSpec):
    try:
        rendered = render_pdf(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(rendered, media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="paper-model.pdf"'})


@app.post("/api/uploads", status_code=201)
async def upload_reference(
    file: UploadFile = File(...),
    view: str = Form(default="other"),
    notes: str = Form(default=""),
):
    """Upload an ephemeral image/PDF. Only a sanitized preview is retained."""
    try:
        data = await file.read(MAX_FILE_BYTES + 1)
        asset = add_asset(data, file.filename or "", view, notes)
        return asset.public()
    except UploadProblem as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    finally:
        await file.close()


@app.get("/api/uploads/{asset_id}")
def get_reference(asset_id: str):
    try:
        return get_asset(asset_id).public()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc


@app.get("/api/uploads/{asset_id}/preview")
def preview_reference(asset_id: str):
    try:
        asset = get_asset(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    return Response(
        asset.preview,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.delete("/api/uploads/{asset_id}", status_code=204)
def remove_reference(asset_id: str):
    if not delete_asset(asset_id):
        raise HTTPException(status_code=404, detail="資料が存在しません。")
    return Response(status_code=204)
