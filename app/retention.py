"""Persist rendered SVG/PDF and generated models; references remain temporary."""
import asyncio
import hashlib
import os
import re
import shutil
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.formparsers import MultiPartParser

# The bounded request body remains in RAM; Starlette must not spool source files.
MAX_BODY = 16 * 1024 * 1024
MultiPartParser.spool_max_size = MAX_BODY + 1
_output_lock = threading.RLock()
router = APIRouter(prefix="/api/outputs", tags=["outputs"])


def root():
    return Path(os.environ.get("PAPER_MODELAR_DATA_DIR", "/data"))


def purge_legacy_sources():
    """One-way migration of this app's old reference library; no backup copies."""
    for path in [root()/"projects", *(root()/name for name in ("library.sqlite3", "library.sqlite3-wal", "library.sqlite3-shm", "library.sqlite3-journal"))]:
        if path.is_symlink() or path.is_file(): path.unlink()
        elif path.is_dir(): shutil.rmtree(path)


def save_output(content, extension):
    if extension not in {"svg", "pdf"}: raise ValueError("Output format")
    content = content.encode() if isinstance(content, str) else content
    folder = root()/"outputs"; folder.mkdir(parents=True, exist_ok=True)
    output_id = hashlib.sha256(content).hexdigest()+"."+extension
    target = folder/output_id
    with _output_lock:
        if not target.exists():
            # Store final bytes only, with no sidecar input, source URL or credentials.
            with target.open("xb") as stream: stream.write(content)
    return output_id


@router.get("")
def index():
    folder = root()/"outputs"
    files = sorted(folder.iterdir(), key=lambda p:p.stat().st_mtime, reverse=True) if folder.exists() else []
    return {"outputs": [{"id":p.name,"bytes":p.stat().st_size,"url":"/api/outputs/"+p.name}
                        for p in files if re.fullmatch(r"[a-f0-9]{64}\.(pdf|svg)",p.name) and p.is_file() and not p.is_symlink()]}


def output_path(output_id):
    if not re.fullmatch(r"[a-f0-9]{64}\.(pdf|svg)",output_id): raise HTTPException(404,"展開図が見つかりません。")
    path = root()/"outputs"/output_id
    if not path.is_file() or path.is_symlink(): raise HTTPException(404,"展開図が見つかりません。")
    return path


@router.get("/{output_id}")
def download(output_id):
    return FileResponse(output_path(output_id), filename="paper-net."+output_id.rsplit(".",1)[1], headers={"Cache-Control":"no-store"})


@router.delete("/{output_id}",status_code=204)
def delete(output_id):
    output_path(output_id).unlink()


def prune_temporary():
    from . import projects, uploads, image_models, mesh_routes
    projects.prune()
    with uploads._lock: uploads._prune()
    image_models.prune(); mesh_routes._prune()


@asynccontextmanager
async def lifespan(app):
    purge_legacy_sources()
    async def cleanup():
        while True:
            await asyncio.sleep(30)
            prune_temporary()
    task=asyncio.create_task(cleanup())
    try: yield
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        from . import projects, uploads, image_models, mesh_routes
        projects._projects.clear(); projects._assets.clear()
        uploads._store.clear(); image_models._images.clear(); mesh_routes._jobs.clear()


class MemoryBodyLimit:
    """Bound multipart bodies before parsing, including chunked requests."""
    def __init__(self, app): self.app=app
    async def __call__(self, scope, receive, send):
        if scope['type']!='http' or scope.get('method') not in {'POST','PATCH','PUT'}:
            return await self.app(scope,receive,send)
        chunks=[]; total=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect': return
            total+=len(message.get('body',b''))
            if total>MAX_BODY:
                from starlette.responses import JSONResponse
                return await JSONResponse({'detail':'送信データは16MB以内にしてください。'},status_code=413)(scope,receive,send)
            chunks.append(message)
            if not message.get('more_body',False): break
        async def replay():
            return chunks.pop(0) if chunks else await receive()
        await self.app(scope,replay,send)
