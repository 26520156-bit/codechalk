"""Bảng xếp hạng toàn hệ thống theo XP hoặc Bcoins."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import optional_user
from ..models import ChallengeProgress, User
from ..schemas import user_out

router = APIRouter(prefix="/api/leaderboard", tags=["Bảng xếp hạng"])


@router.get("")
def board(by: str = "xp", limit: int = 50, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    if by not in ("xp", "bcoins"):
        raise HTTPException(400, "by phải là xp hoặc bcoins.")
    col = User.xp if by == "xp" else User.bcoins
    limit = max(1, min(limit, 200))
    rows = db.scalars(select(User).where(User.is_active.is_(True), User.role != "HOST").order_by(col.desc(), User.id).limit(limit)).all()
    solved = dict(db.execute(select(ChallengeProgress.user_id, func.count()).where(ChallengeProgress.solved_at.is_not(None))
                             .group_by(ChallengeProgress.user_id)).all())
    out = []
    for i, u in enumerate(rows, start=1):
        d = user_out(u)
        d.update(rank=i, solved=solved.get(u.id, 0), is_me=bool(user and user.id == u.id))
        out.append(d)
    me = None
    if user and user.role != "HOST":
        val = getattr(user, by)
        better = db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True), User.role != "HOST", col > val))
        me = {"rank": (better or 0) + 1, "value": val}
    return {"by": by, "rows": out, "me": me}
