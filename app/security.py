"""Băm mật khẩu (bcrypt) và mã thông báo đăng nhập JWT."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from datetime import datetime, timedelta, timezone

import jwt

from .config import settings

log = logging.getLogger("codechalk.security")

try:  # bcrypt là bắt buộc khi chạy thật (requirements.txt)
    import bcrypt as _bcrypt
except ImportError:  # pragma: no cover - chỉ xảy ra trên máy thiếu thư viện
    _bcrypt = None
    if settings.is_production:
        raise RuntimeError("Thiếu thư viện bcrypt: chạy 'pip install -r requirements.txt'.")
    log.warning("Không có bcrypt: tạm dùng PBKDF2-SHA256 (chỉ nên dùng khi thử nghiệm).")

ALGO = "HS256"
PBKDF2_ROUNDS = 240_000


def hash_password(password: str) -> str:
    if _bcrypt is not None:
        return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("ascii")
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ROUNDS, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, hashed: str) -> bool:
    try:
        if hashed.startswith("$2"):
            if _bcrypt is None:
                return False
            return _bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
        if hashed.startswith("pbkdf2_sha256$"):
            _, rounds, salt, dk = hashed.split("$")
            calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(rounds))
            return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False
    return False


def needs_rehash(hashed: str) -> bool:
    """Mật khẩu băm bằng PBKDF2 (lúc máy thiếu bcrypt) được đổi sang bcrypt ở lần đăng nhập kế tiếp."""
    return _bcrypt is not None and not hashed.startswith("$2")


def create_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": now + timedelta(days=settings.jwt_days)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGO)


def decode_token(token: str) -> int | None:
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=[ALGO])
        return int(data["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
