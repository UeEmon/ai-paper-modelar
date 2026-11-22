"""HTTP entrypoint for AI Paper Modelar."""
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .ai import ProposalRequest, proposals, credentials_from_headers, check_connection, available_models, local_defaults
from .generator import ModelSpec, render_pdf, render_svg, summary
from .research import research
from .senrolab import router as senrolab_router
from .mesh_routes import router as mesh_router
from .project_routes import router as project_router
from .image_models import router as image_model_router
from .projects import LibraryProblem
from .uploads import add_asset, get_asset, delete_asset, UploadProblem, MAX_FILE_BYTES

HERE = Path(__file__).resolve().parent
from .retention import lifespan, MemoryBodyLimit, router as output_router, save_output

app = FastAPI(title="AI Paper Modelar", version="0.1.0", lifespan=lifespan)
app.add_middleware(MemoryBodyLimit)
app.include_router(output_router)
app.include_router(senrolab_router)
app.include_router(mesh_router)
app.include_router(project_router)
app.include_router(image_model_router)
from .external_3d import router as external_3d_router
app.include_router(external_3d_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# SenroLab 向けの /v1/ は、エラーを {"error": "日本語のメッセージ"} で返す（docs/senrolab/openapi.yaml）
@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/v1/"):
        return JSONResponse({"error": "入力が正しくありません"}, status_code=400)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "入力値を確認してください。"}, status_code=422)
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/v1/"):
        message = exc.detail if isinstance(exc.detail, str) else "エラーになりました"
        return JSONResponse({"error": message}, status_code=exc.status_code, headers=exc.headers)
    return await http_exception_handler(request, exc)


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

@app.get("/", include_in_schema=False)
def homepage():
    return FileResponse(HERE / "static" / "index.html")

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/research")
async def find(q: str = Query(min_length=2, max_length=120),
               scope: Literal["all", "web", "wikipedia"] = "all"):
    try:
        return await research(q, scope)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="公開資料を取得できませんでした") from exc

@app.post("/api/proposals")
async def plan(req: ProposalRequest, request: Request):
    try:
        credentials = credentials_from_headers(request.headers)
    except ValueError:
        raise HTTPException(status_code=400, detail="AI設定を確認してください。") from None
    try:
        return JSONResponse(await proposals(req, credentials), headers={"Cache-Control": "no-store"})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except LibraryProblem as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

@app.get("/api/ai/local-config")
def local_ai_config():
    return JSONResponse(local_defaults(), headers={"Cache-Control": "no-store"})


@app.post("/api/ai/test")
async def test_ai_connection(request: Request):
    try:
        credentials = credentials_from_headers(request.headers)
        if credentials is None:
            raise ValueError("Missing credentials")
    except ValueError:
        return JSONResponse({"ok": False, "message": "AI設定を確認してください。接続先はサーバーの許可URLに限られます。"}, status_code=400)
    mode = request.headers.get("x-ai-test-mode", "text")
    if mode not in {"text", "image"}:
        return JSONResponse({"ok": False, "message": "接続テストの方式を確認してください。"}, status_code=400)
    code, result = await check_connection(credentials, vision_test=mode == "image")
    return JSONResponse(result, status_code=code)


@app.post("/api/ai/models")
async def list_ai_models(request: Request):
    try:
        credentials = credentials_from_headers({**request.headers,
            "x-ai-model": "model-list"})
        if credentials is None:
            raise ValueError("Missing credentials")
    except ValueError:
        return JSONResponse({"ok": False, "message": "AI設定を確認してください。モデル一覧の取得にはプロバイダーとキー（ローカルは任意）が必要です。"}, status_code=400)
    code, result = await available_models(credentials)
    return JSONResponse(result, status_code=code)


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
    save_output(rendered, "svg")
    return Response(rendered, media_type="image/svg+xml")

@app.post("/api/template.pdf")
def pdf(req: ModelSpec):
    try:
        rendered = render_pdf(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    save_output(rendered, "pdf")
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
