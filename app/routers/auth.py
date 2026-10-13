"""Đăng ký, đăng nhập, hồ sơ cá nhân."""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import active_plans, current_user
from ..models import ROLE_STUDENT, User
from ..schemas import LoginIn, PasswordIn, ProfileIn, RegisterIn, user_out
from ..security import create_token, hash_password, needs_rehash, verify_password
from ..services import access

router = APIRouter(prefix="/api/auth", tags=["Tài khoản"])
_attempts: dict[str, list[float]] = defaultdict(list)
WINDOW, MAX_TRIES = 15 * 60, 10


def _throttle(key: str, limit: int = MAX_TRIES) -> None:
    now = time.time()
    tries = [t for t in _attempts[key] if now - t < WINDOW]
    _attempts[key] = tries
    if len(tries) >= limit:
        raise HTTPException(429, "Đăng nhập sai quá nhiều lần. Thử lại sau 15 phút.")


def me_payload(db: Session, u: User) -> dict:
    d = user_out(u, private=True)
    d["plans"] = sorted(active_plans(db, u))
    d["ai_quota"] = access.ai_quota(db, u)
    d["ai_used_today"] = access.ai_used_today(u)
    return d


@router.post("/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.scalar(select(func.count()).select_from(User).where(User.email == body.email)):
        raise HTTPException(409, "Email này đã được đăng ký.")
    u = User(email=body.email, password_hash=hash_password(body.password), phone=body.phone,
             full_name=body.full_name.strip(), role=ROLE_STUDENT)
    db.add(u)
    db.commit()
    return {"token": create_token(u.id, u.role), "user": me_payload(db, u)}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    key = f"{body.email}|{request.client.host if request.client else ''}"
    _throttle(key)
    _throttle("acc|" + body.email, 3 * MAX_TRIES)      # chặn dò mật khẩu một tài khoản từ nhiều địa chỉ IP
    u = db.scalar(select(User).where(User.email == body.email))
    if not u or not verify_password(body.password, u.password_hash):
        _attempts[key].append(time.time())
        _attempts["acc|" + body.email].append(time.time())
        raise HTTPException(401, "Email hoặc mật khẩu không đúng.")
    if not u.is_active:
        raise HTTPException(403, "Tài khoản đã bị khoá. Liên hệ HOST.")
    _attempts.pop(key, None)
    if needs_rehash(u.password_hash):
        u.password_hash = hash_password(body.password)
    u.last_login_at = utcnow()
    db.commit()
    return {"token": create_token(u.id, u.role), "user": me_payload(db, u)}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return me_payload(db, user)


@router.patch("/me")
def update_me(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.full_name is not None:
        user.full_name = body.full_name.strip()
    if body.phone is not None:
        user.phone = body.phone
    db.commit()
    return me_payload(db, user)


@router.post("/password")
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "Mật khẩu hiện tại không đúng.")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}
