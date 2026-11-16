"""HTTP entrypoint for AI Paper Modelar."""
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .ai import ProposalRequest, proposals
from .generator import ModelSpec, render_pdf, render_svg, summary
from .research import research

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
    return await proposals(req)

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
