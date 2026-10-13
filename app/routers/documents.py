"""Kho tài liệu: tải lên, xem trước PDF, tải xuống."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import ROLE_HOST, Document, User
from ..schemas import iso, user_out
from ..services import storage

router = APIRouter(prefix="/api/documents", tags=["Kho tài liệu"])
CATEGORIES = ["Giáo trình", "Slide bài giảng", "Đề thi", "Bài tập", "Code mẫu", "Tài liệu tham khảo", "Khác"]


def doc_out(d: Document, me: User | None = None) -> dict:
    ext = d.filename.rsplit(".", 1)[-1].lower() if "." in d.filename else ""
    return {"id": d.id, "title": d.title, "description": d.description, "category": d.category, "filename": d.filename,
            "ext": ext, "mime": d.mime, "size": d.size, "downloads": d.downloads, "created_at": iso(d.created_at),
            "uploader": user_out(d.uploader) if d.uploader else None, "previewable": ext in ("pdf", "png", "jpg", "jpeg", "gif", "webp", "txt", "md"),
            "can_delete": bool(me and (me.id == d.uploader_id or me.role == ROLE_HOST))}


@router.get("/categories")
def categories():
    return CATEGORIES


@router.get("")
def list_docs(q: str = "", category: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Document).order_by(Document.id.desc()).limit(300)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Document.title).like(like), func.lower(Document.description).like(like)))
    if category:
        stmt = stmt.where(Document.category == category)
    return [doc_out(d, user) for d in db.scalars(stmt).all()]


@router.post("", status_code=201)
async def upload(file: UploadFile = File(...), title: str = Form(...), description: str = Form(""), category: str = Form("Khác"),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    title = title.strip()[:200]
    if len(title) < 2:
        raise HTTPException(400, "Nhập tên tài liệu.")
    if category not in CATEGORIES:
        category = "Khác"
    rel, original, mime, size = await storage.save(file, "docs", storage.DOC_EXT)
    d = Document(uploader_id=user.id, title=title, description=description[:3000], category=category, filename=original,
                 stored_name=rel, mime=mime, size=size)
    db.add(d)
    db.commit()
    db.refresh(d)
    return doc_out(d, user)


@router.get("/{did}/file")
def download(did: int, inline: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Document, did)
    if not d:
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    path = storage.abs_path(d.stored_name)
    if not path.exists():
        raise HTTPException(410, "Tệp đã bị xoá khỏi máy chủ.")
    if not inline:
        d.downloads += 1
        db.commit()
    disp = "inline" if inline else "attachment"
    return FileResponse(path, media_type=d.mime if inline else "application/octet-stream",
                        headers={"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(d.filename)}",
                                 "X-Content-Type-Options": "nosniff"})


@router.delete("/{did}")
def delete(did: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Document, did)
    if not d:
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    if d.uploader_id != user.id and user.role != ROLE_HOST:
        raise HTTPException(403, "Chỉ người đăng hoặc HOST được xoá.")
    storage.abs_path(d.stored_name).unlink(missing_ok=True)
    db.delete(d)
    db.commit()
    return {"ok": True}
