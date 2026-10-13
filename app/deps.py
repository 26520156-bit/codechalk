"""Phụ thuộc dùng chung cho các router: phiên CSDL, người dùng hiện tại, kiểm tra quyền."""
from __future__ import annotations

from datetime import timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db, utcnow
from .models import PLAN_SELF, ROLE_HOST, ROLE_TEACHER, User, UserPlan
from .security import decode_token


def _token_from(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token")  # dùng cho tải tệp / WebSocket


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    tok = _token_from(request)
    if not tok:
        return None
    uid = decode_token(tok)
    if uid is None:
        return None
    user = db.get(User, uid)
    return user if user and user.is_active else None


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bạn cần đăng nhập.")
    return user


def require_teacher(user: User = Depends(current_user)) -> User:
    if user.role not in (ROLE_TEACHER, ROLE_HOST):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ GIÁO VIÊN hoặc HOST mới làm được thao tác này.")
    return user


def require_host(user: User = Depends(current_user)) -> User:
    if user.role != ROLE_HOST:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ HOST mới làm được thao tác này.")
    return user


def active_plans(db: Session, user: User) -> set[str]:
    """Các phiên bản người dùng đang được dùng. HOST và GIÁO VIÊN dùng được mọi phiên bản."""
    if user.role in (ROLE_HOST,):
        return {"TU_HOC", "ON_THI", "LOP_HOC"}
    now = utcnow()
    rows = db.scalars(select(UserPlan).where(UserPlan.user_id == user.id)).all()
    plans = {PLAN_SELF}
    for r in rows:
        exp = r.expires_at
        if exp is None or exp.astimezone(timezone.utc) > now:
            plans.add(r.plan_id)
    return plans
