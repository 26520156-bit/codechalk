"""Lưu tệp tải lên vào thư mục data/uploads (đổi tên ngẫu nhiên, giới hạn dung lượng và loại tệp)."""
from __future__ import annotations

import mimetypes
import os
import re
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile

from ..config import settings

DOC_EXT = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip", ".rar", ".7z", ".txt", ".md", ".csv",
           ".png", ".jpg", ".jpeg", ".gif", ".webp", ".cpp", ".c", ".h", ".hpp", ".py", ".java", ".js", ".ipynb", ".json"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def safe_name(name: str) -> str:
    base = os.path.basename(name or "tep")
    base = re.sub(r"[^\w.\- ()À-ỹ]", "_", base)[:180]
    return base or "tep"


async def save(upload: UploadFile, folder: str, allowed: set[str]) -> tuple[str, str, str, int]:
    """Trả về (đường dẫn tương đối, tên gốc, mime, kích thước)."""
    original = safe_name(upload.filename or "tep")
    ext = Path(original).suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"Không nhận loại tệp {ext or '(không đuôi)'}.")
    limit = settings.max_upload_mb * 1024 * 1024
    d = settings.upload_dir / folder
    d.mkdir(parents=True, exist_ok=True)
    stored = f"{secrets.token_hex(12)}{ext}"
    path = d / stored
    size = 0
    with path.open("wb") as f:
        while chunk := await upload.read(1024 * 256):
            size += len(chunk)
            if size > limit:
                f.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, f"Tệp vượt quá {settings.max_upload_mb} MB.")
            f.write(chunk)
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(400, "Tệp rỗng.")
    mime = upload.content_type or mimetypes.guess_type(original)[0] or "application/octet-stream"
    if ext in IMG_EXT:
        head = path.read_bytes()[:12]
        if not (head.startswith(b"\x89PNG") or head[:3] == b"\xff\xd8\xff" or head[:4] == b"GIF8" or head[8:12] == b"WEBP"):
            path.unlink(missing_ok=True)
            raise HTTPException(400, "Tệp ảnh không hợp lệ.")
    return f"{folder}/{stored}", original, mime, size


def abs_path(rel: str) -> Path:
    p = (settings.upload_dir / rel).resolve()
    if settings.upload_dir.resolve() not in p.parents:
        raise HTTPException(400, "Đường dẫn không hợp lệ.")
    return p
