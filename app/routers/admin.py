"""Bảng điều khiển của HOST: tài khoản, vai trò, thống kê, sổ Bcoins."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import active_plans, require_host
from ..models import (PENDING, ROLE_HOST, BcoinTransaction, CashoutRequest, Contest, Document, PaymentOrder, Submission, User)
from ..schemas import AdminUserIn, AIConfigIn, iso, user_out
from ..services import ai as ai_service
from ..services.notify import notify

router = APIRouter(prefix="/api/admin", tags=["HOST"])


@router.get("/stats")
def stats(host: User = Depends(require_host), db: Session = Depends(get_db)):
    c = lambda q: db.scalar(q) or 0  # noqa: E731
    return {
        "users": c(select(func.count()).select_from(User)),
        "teachers": c(select(func.count()).select_from(User).where(User.role == "TEACHER")),
        "pending_payments": c(select(func.count()).select_from(PaymentOrder).where(PaymentOrder.status == PENDING)),
        "pending_cashouts": c(select(func.count()).select_from(CashoutRequest).where(CashoutRequest.status == PENDING)),
        "contests": c(select(func.count()).select_from(Contest)),
        "submissions": c(select(func.count()).select_from(Submission)),
        "documents": c(select(func.count()).select_from(Document)),
        "bcoins_total": c(select(func.sum(User.bcoins))),
    }


@router.get("/users")
def users(q: str = "", role: str = "", page: int = 1, host: User = Depends(require_host), db: Session = Depends(get_db)):
    stmt = select(User)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.full_name).like(like), User.phone.like(like)))
    if role:
        stmt = stmt.where(User.role == role)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.id.desc()).offset((max(page, 1) - 1) * 50).limit(50)).all()
    out = []
    for u in rows:
        d = user_out(u, private=True)
        d["plans"] = sorted(active_plans(db, u))
        out.append(d)
    return {"total": total, "page": page, "items": out}


@router.patch("/users/{uid}")
def edit_user(uid: int, body: AdminUserIn, host: User = Depends(require_host), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Không tìm thấy tài khoản.")
    if u.role == ROLE_HOST and (body.role is not None or body.is_active is False):
        raise HTTPException(400, "Không đổi vai trò hay khoá tài khoản HOST.")
    data = body.model_dump(exclude_none=True)
    if "email" in data and data["email"] != u.email:
        if db.scalar(select(func.count()).select_from(User).where(User.email == data["email"])):
            raise HTTPException(409, "Email đã được dùng.")
    old_role = u.role
    for k, v in data.items():
        setattr(u, k, v)
    db.commit()
    if body.role and body.role != old_role:
        label = "GIÁO VIÊN" if body.role == "TEACHER" else "SINH VIÊN"
        notify(db, u, f"Vai trò của bạn đã đổi thành {label}",
               "Bạn có thể tạo Phòng Kiểm tra cho lớp." if body.role == "TEACHER" else "", "/#tai-khoan")
    d = user_out(u, private=True)
    d["plans"] = sorted(active_plans(db, u))
    return d


@router.get("/bcoins")
def ledger(user_id: int | None = None, host: User = Depends(require_host), db: Session = Depends(get_db)):
    q = select(BcoinTransaction).order_by(BcoinTransaction.id.desc()).limit(300)
    if user_id:
        q = q.where(BcoinTransaction.user_id == user_id)
    names = {u.id: (u.full_name or u.email) for u in db.scalars(select(User)).all()}
    return [{"id": t.id, "user_id": t.user_id, "user": names.get(t.user_id, "?"), "amount": t.amount, "balance_after": t.balance_after,
             "reason": t.reason, "note": t.note, "created_at": iso(t.created_at)} for t in db.scalars(q).all()]


# ---------- Cấu hình AI (ghi đè AI_PROVIDER / AI_API_KEY trong .env) ----------
def _ai_state() -> dict:
    c = ai_service.cfg()
    key = c["key"] or ""
    return {"providers": [{"id": k, "name": v["name"], "model": v["model"], "needs_key": v["key"], "key_url": v["key_url"],
                           "key_hint": v["key_hint"], "base": v.get("base", "")} for k, v in ai_service.PROVIDERS.items()],
            "provider": c["provider"] if c["provider"] in ai_service.PROVIDERS else "none", "model": c["model"],
            "effective_model": ai_service.model_name() if ai_service.enabled() else "", "base_url": c["base"],
            "key_set": bool(key), "key_hint": ("…" + key[-4:]) if len(key) >= 8 else ("đã lưu" if key else ""),
            "source": c["source"], "enabled": ai_service.enabled()}


def _resolve(body: AIConfigIn) -> dict:
    """Cấu hình HOST vừa nhập; bỏ trống khoá thì dùng khoá đang lưu (nếu cùng nhà cung cấp)."""
    cur = ai_service.cfg()
    key = body.api_key.strip() if body.api_key is not None else (cur["key"] if cur["provider"] == body.provider else "")
    return {"provider": body.provider, "key": key, "model": body.model.strip(), "base": body.base_url, "source": "admin"}


@router.get("/ai")
def ai_get(host: User = Depends(require_host)):
    return _ai_state()


@router.put("/ai")
def ai_put(body: AIConfigIn, host: User = Depends(require_host), db: Session = Depends(get_db)):
    c = _resolve(body)
    meta = ai_service.PROVIDERS.get(c["provider"])
    if meta and meta["key"] and not c["key"]:
        raise HTTPException(400, f"Dán khoá API của {meta['name']} trước khi lưu.")
    if c["provider"] == "ollama" and not c["model"]:
        raise HTTPException(400, "Chọn model Ollama (bấm “Tải danh sách model”).")
    ai_service.save_db_config(db, {"ai.provider": c["provider"], "ai.api_key": c["key"], "ai.model": c["model"],
                                   "ai.base_url": c["base"]})
    return _ai_state()


@router.post("/ai/models")
async def ai_models(body: AIConfigIn, host: User = Depends(require_host)):
    c = _resolve(body)
    meta = ai_service.PROVIDERS.get(c["provider"])
    if not meta:
        raise HTTPException(400, "Chọn nhà cung cấp AI trước.")
    if meta["key"] and not c["key"]:
        raise HTTPException(400, "Dán khoá API trước để tải danh sách model.")
    try:
        models = await asyncio.to_thread(ai_service.list_models, c["provider"], c["key"], c["base"])
    except ai_service.AIUnavailable as e:
        raise HTTPException(400, str(e)) from None
    return {"models": models, "recommended": meta["model"]}


@router.post("/ai/test")
async def ai_test(body: AIConfigIn, host: User = Depends(require_host)):
    c = _resolve(body)
    if c["provider"] not in ai_service.PROVIDERS:
        raise HTTPException(400, "Chọn nhà cung cấp AI trước.")
    t0 = time.perf_counter()
    try:
        reply = await ai_service.complete("", "Kiểm tra kết nối. Hãy trả lời đúng một từ: OK", max_tokens=60, c=c)
    except ai_service.AIUnavailable as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True, "ms": int((time.perf_counter() - t0) * 1000), "reply": reply.strip()[:120],
            "model": c["model"] or ai_service.DEFAULT_MODEL.get(c["provider"], "")}
