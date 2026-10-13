"""Trợ lý lập trình AI: gợi ý, chỉ lỗi; và cổng AI cho Robot Trợ giảng trên trang web."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Challenge, ContestProblem, User
from ..schemas import TutorIn
from ..services import access, ai

router = APIRouter(prefix="/api/ai", tags=["AI"])


class TutorReq(TutorIn):
    challenge_id: int | None = None
    problem_id: int | None = None


class CompleteReq(BaseModel):
    prompt: str = Field(min_length=1, max_length=120_000)
    json_mode: bool = False


@router.get("/status")
def status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"enabled": ai.enabled(), "provider": ai.cfg()["provider"] if ai.enabled() else None, "is_host": user.role == "HOST", "model": ai.model_name() if ai.enabled() else None,
            "quota": access.ai_quota(db, user), "used_today": access.ai_used_today(user)}


@router.post("/tutor")
async def tutor(body: TutorReq, user: User = Depends(current_user), db: Session = Depends(get_db)):
    statement = ""
    if body.challenge_id:
        c = db.get(Challenge, body.challenge_id)
        if c:
            if not access.can_open_chapter(db, user, c.chapter):
                raise HTTPException(402, "Bài này thuộc gói Ôn thi hoặc Lớp học.")
            statement = f"Bài {c.id}: {c.title}\n{c.statement}\n{c.input_format}\n{c.output_format}"
    elif body.problem_id:
        p = db.get(ContestProblem, body.problem_id)
        if p and p.contest.grading_mode:  # trong phòng thi đang diễn ra không cho hỏi AI để giữ công bằng
            from ..services.contests import state_of
            if state_of(p.contest) == "ONGOING" and p.contest.creator_id != user.id:
                raise HTTPException(403, "Không dùng trợ lý AI trong lúc phòng thi đang diễn ra.")
            statement = f"{p.title}\n{p.statement}"
    used, limit = access.take_ai_credit(db, user)
    try:
        text = await ai.tutor(body.mode, statement, body.language, body.code, body.question, body.verdict, body.error)
    except ai.AIUnavailable as e:
        raise HTTPException(503, str(e)) from None
    return {"answer": text, "used_today": used, "quota": limit}


@router.post("/complete")
async def complete(body: CompleteReq, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Cổng AI cho Robot Trợ giảng của trang web khi trang chạy trên server (khoá API nằm ở server, không lộ ra trình duyệt)."""
    used, limit = access.take_ai_credit(db, user)
    try:
        text = await ai.complete("", body.prompt, want_json=body.json_mode, max_tokens=4096)
    except ai.AIUnavailable as e:
        raise HTTPException(503, str(e)) from None
    return {"text": text, "used_today": used, "quota": limit}
