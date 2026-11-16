"""Temporary, local-only source uploads for AI reference proposals.

Data never lands in a persistent volume. Files expire after an hour. Only
metadata, a sanitized JPEG preview and limited PDF text are kept in memory.
Uploads are not publicly searchable: access requires an unpredictable asset id.
"""
from __future__ import annotations

import io
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import PurePath

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_ASSETS = 24
TTL_SECONDS = 3600
MAX_PIXELS = 24_000_000
MAX_PDF_PAGES = 20
MAX_PDF_TEXT = 6000
VIEWS = {"front", "back", "left", "right", "roof", "plan", "detail", "other"}
EXTENSIONS = {".jpeg", ".jpg", ".png", ".webp", ".pdf"}

_store: dict[str, "Asset"] = {}
_lock = threading.RLock()


class UploadProblem(Exception):
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.status_code = status_code


@dataclass
class Asset:
    id: str
    name: str
    kind: str
    view: str
    notes: str
    uploaded_bytes: int
    preview: bytes = field(repr=False)
    excerpt: str = field(default="", repr=False)
    created_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "view": self.view,
            "notes": self.notes,
            "size_bytes": self.uploaded_bytes,
            "has_text": bool(self.excerpt),
            "preview_url": "/api/uploads/" + self.id + "/preview",
            "expires_at": round(self.created_at + TTL_SECONDS),
        }


def _prune() -> None:
    now = time.time()
    for key, asset in list(_store.items()):
        if now - asset.created_at >= TTL_SECONDS:
            del _store[key]


def get_asset(asset_id: str) -> Asset:
    with _lock:
        _prune()
        if asset_id not in _store:
            raise KeyError("資料の有効期限が切れたか、削除されています。再アップロードしてください。")
        return _store[asset_id]


def delete_asset(asset_id: str) -> bool:
    with _lock:
        _prune()
        return _store.pop(asset_id, None) is not None


def _preview_jpeg(img: Image.Image) -> bytes:
    if img.width * img.height > MAX_PIXELS:
        raise UploadProblem("画像が大きすぎます（最大2400万画素）。", 413)
    img = ImageOps.exif_transpose(img)
    img.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
    if img.mode != "RGB":
        background = Image.new("RGB", img.size, (255, 255, 255))
        if "A" in img.getbands():
            background.paste(img, mask=img.getchannel("A"))
        else:
            background.paste(img)
        img = background
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=82, optimize=True)
    return out.getvalue()


def _prepare_image(data: bytes) -> tuple[bytes, str]:
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise UploadProblem("対応する画像形式はJPEG・PNG・WebPです。", 415)
            image.load()
            return _preview_jpeg(image), "image"
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise UploadProblem("画像を読み込めません。破損または不正な形式です。", 415) from exc


def _prepare_pdf(data: bytes) -> tuple[bytes, str, str]:
    if not data.startswith(b"%PDF-"):
        raise UploadProblem("PDFファイルとして認識できません。", 415)
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise UploadProblem("パスワード付きPDFには対応していません。", 415)
        if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
            raise UploadProblem("PDFは20ページ以内にしてください。", 413)
        texts = []
        for page in list(reader.pages)[:5]:
            if sum(len(x) for x in texts) >= MAX_PDF_TEXT:
                break
            texts.append((page.extract_text() or "")[:MAX_PDF_TEXT])
        excerpt = "\n".join(texts)[:MAX_PDF_TEXT]
        document = pdfium.PdfDocument(data)
        try:
            page = document[0]
            try:
                bitmap = page.render(scale=1.6)
                img = bitmap.to_pil()
                try:
                    preview = _preview_jpeg(img)
                finally:
                    img.close()
                    bitmap.close()
            finally:
                page.close()
        finally:
            document.close()
        return preview, "pdf", excerpt
    except UploadProblem:
        raise
    except Exception as exc:
        raise UploadProblem("PDFを解析できません。別のファイルをお試しください。", 415) from exc


def add_asset(data: bytes, filename: str, view: str, notes: str = "") -> Asset:
    if not data:
        raise UploadProblem("空のファイルは登録できません。", 422)
    if len(data) > MAX_FILE_BYTES:
        raise UploadProblem("ファイルは15MB以内にしてください。", 413)
    name = PurePath((filename or "").replace("\\", "/")).name[:120]
    if not name or re.search(r"[\x00-\x1f\x7f]", name):
        raise UploadProblem("ファイル名が不正です。")
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in EXTENSIONS:
        raise UploadProblem("JPEG・PNG・WebP・PDFファイルに対応しています。", 415)
    if view not in VIEWS:
        raise UploadProblem("資料の向きを指定し直してください。")
    notes = (notes or "").strip()
    if len(notes) > 400:
        raise UploadProblem("メモは400文字以内です。")

    if ext == ".pdf":
        preview, kind, excerpt = _prepare_pdf(data)
    else:
        preview, kind = _prepare_image(data)
        excerpt = ""

    asset = Asset(
        id=uuid.uuid4().hex,
        name=name,
        kind=kind,
        view=view,
        notes=notes,
        uploaded_bytes=len(data),
        preview=preview,
        excerpt=excerpt,
    )
    with _lock:
        _prune()
        if len(_store) >= MAX_ASSETS:
            raise UploadProblem("一時保管の上限に達しました。不要な資料を削除してください。", 429)
        _store[asset.id] = asset
    return asset
