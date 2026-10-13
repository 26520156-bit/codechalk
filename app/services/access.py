"""Quyền theo phiên bản (gói) và hạn mức AI mỗi ngày."""
from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..deps import active_plans
from ..models import PLAN_CLASS, PLAN_EXAM, ROLE_HOST, ROLE_TEACHER, User

FREE_CHAPTERS = {1, 2, 3, 4, 5}                 # Tự học: chương 1–5 của bộ 1000 bài
AI_DAILY = {"TU_HOC": 20, "ON_THI": 300, "LOP_HOC": 300}
VN = timezone(timedelta(hours=7))

_lock = threading.Lock()
_ai_used: dict[tuple[int, str], int] = defaultdict(int)


def can_open_chapter(db: Session, user: User | None, chapter: int) -> bool:
    if chapter in FREE_CHAPTERS:
        return True
    if user is None:
        return False
    return bool(active_plans(db, user) & {PLAN_EXAM, PLAN_CLASS})


def can_use_ai_grading(db: Session, user: User) -> bool:
    return user.role in (ROLE_TEACHER, ROLE_HOST) or PLAN_CLASS in active_plans(db, user)


def ai_quota(db: Session, user: User) -> int:
    if user.role in (ROLE_TEACHER, ROLE_HOST):
        return 1000
    return max(AI_DAILY.get(p, 0) for p in active_plans(db, user))


def take_ai_credit(db: Session, user: User) -> tuple[int, int]:
    """Trừ một lượt AI trong ngày (giờ Việt Nam). Trả về (đã dùng, hạn mức)."""
    day = datetime.now(VN).strftime("%Y-%m-%d")
    limit = ai_quota(db, user)
    with _lock:
        used = _ai_used[(user.id, day)]
        if used >= limit:
            raise HTTPException(429, f"Bạn đã dùng hết {limit} lượt hỏi AI hôm nay. Nâng cấp gói Ôn thi để có thêm lượt.")
        _ai_used[(user.id, day)] = used + 1
        return used + 1, limit


def ai_used_today(user: User) -> int:
    return _ai_used[(user.id, datetime.now(VN).strftime("%Y-%m-%d"))]
