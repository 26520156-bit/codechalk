"""Dữ liệu khởi tạo: các gói dịch vụ, tài khoản HOST, bộ 1000 bài Challenge."""
from __future__ import annotations

import json
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import ROOT, settings
from .models import ROLE_HOST, Challenge, ChallengeTest, Plan, User
from .security import hash_password

log = logging.getLogger("codechalk.seed")

PLANS = [
    {"id": "TU_HOC", "name": "Tự học", "price_vnd": 0, "duration_days": 0, "sort_order": 1,
     "description": "Cho bạn mới bắt đầu hoặc học lại từ đầu.",
     "features": ["Lớp học C++ và Python", "Challenge chương 1 đến 5", "Code War, Forum, Kho tài liệu", "20 lượt hỏi AI mỗi ngày"]},
    {"id": "ON_THI", "name": "Ôn thi", "price_vnd": 59000, "duration_days": 30, "sort_order": 2,
     "description": "Cho kỳ cuối, ICPC, Olympic Tin học sinh viên.",
     "features": ["Mọi thứ của gói Tự học", "Challenge đủ 13 chương (1000 bài)", "300 lượt hỏi AI mỗi ngày", "Gợi ý 3 bậc và chỉ lỗi chi tiết"]},
    {"id": "LOP_HOC", "name": "Lớp học", "price_vnd": 19000, "duration_days": 30, "sort_order": 3,
     "description": "Cho giảng viên, trợ giảng và câu lạc bộ lập trình.",
     "features": ["Mọi thứ của gói Ôn thi", "Tạo phòng Code War chấm bằng AI", "Báo cáo bài nộp của phòng", "Ưu tiên hỗ trợ"]},
]


def seed_plans(db: Session) -> None:
    for p in PLANS:
        if db.get(Plan, p["id"]) is None:
            db.add(Plan(**p))
    db.commit()


def seed_host(db: Session) -> None:
    if not settings.host_email or not settings.host_password:
        log.warning("Chưa đặt HOST_EMAIL / HOST_PASSWORD trong .env: chưa tạo tài khoản HOST.")
        return
    email = settings.host_email.strip().lower()
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        db.add(User(email=email, password_hash=hash_password(settings.host_password), phone=settings.host_phone or "",
                    full_name=settings.host_name, role=ROLE_HOST))
        db.commit()
        log.info("Đã tạo tài khoản HOST %s", email)
    elif u.role != ROLE_HOST:
        u.role = ROLE_HOST
        db.commit()


def seed_challenges(db: Session, path=None, force: bool = False) -> int:
    """Nạp data/challenges.json. Chỉ nạp khi bảng trống (hoặc force=True: cập nhật đề và test)."""
    path = path or ROOT / "data" / "challenges.json"
    if not path.exists():
        return 0
    if not force and db.scalar(select(func.count()).select_from(Challenge)):
        return 0
    items = json.loads(path.read_text(encoding="utf-8"))
    for it in items:
        c = db.get(Challenge, it["id"])
        if c is None:
            c = Challenge(id=it["id"])
            db.add(c)
        for k in ("chapter", "chapter_title", "section", "title", "statement", "input_format", "output_format", "samples",
                  "difficulty", "time_limit_ms", "memory_mb", "xp"):
            if k in it:
                setattr(c, k, it[k])
        tests = it.get("tests") or []
        c.tests.clear()
        for j, t in enumerate(tests, start=1):
            c.tests.append(ChallengeTest(position=j, input=t["input"], expected_output=t["output"], is_sample=t.get("sample", False)))
        c.has_tests = bool(tests)
    db.commit()
    return len(items)
