"""Trạng thái phòng thi, chấm điểm, xếp hạng và trả thưởng Bcoins."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..models import (CONTEST_CODEWAR, DONE, ONGOING, UPCOMING, Contest, ContestProblem, Participant, Submission, User)
from . import bcoins
from .notify import notify

log = logging.getLogger("codechalk.contests")


def state_of(c: Contest, now: datetime | None = None) -> str:
    now = now or utcnow()
    if now < c.start_at:
        return UPCOMING
    if now < c.end_at:
        return ONGOING
    return DONE


def participant_deadline(c: Contest, joined_at: datetime) -> datetime:
    return min(joined_at + timedelta(minutes=c.duration_minutes), c.end_at)


def problem_score(sub: Submission) -> float:
    return float(sub.score or 0)


def recompute_participant(db: Session, c: Contest, p: Participant, when: datetime) -> None:
    """Điểm = tổng (điểm tốt nhất của từng bài / 100 × điểm tối đa của bài)."""
    best: dict[int, float] = {}
    for s in db.scalars(select(Submission).where(Submission.contest_id == c.id, Submission.user_id == p.user_id,
                                                 Submission.status == "DONE", Submission.created_at <= p.deadline_at)):
        best[s.problem_id] = max(best.get(s.problem_id, 0.0), problem_score(s))
    total = 0.0
    for prob in c.problems:
        total += prob.points * best.get(prob.id, 0.0) / 100
    total = round(total, 2)
    if total > (p.score or 0):
        p.last_improve_at = when
    p.score = total


def ranking(db: Session, c: Contest) -> list[Participant]:
    parts = db.scalars(select(Participant).where(Participant.contest_id == c.id)).all()

    def key(p: Participant):
        elapsed = (p.last_improve_at - p.joined_at).total_seconds() if p.last_improve_at else 10 ** 9
        return (-(p.score or 0), elapsed, p.joined_at)
    return sorted(parts, key=key)


def finalize(db: Session, c: Contest) -> None:
    """Chốt bảng xếp hạng khi phòng sang DONE và cộng Bcoins cho Top 10."""
    if c.finalized_at is not None:
        return
    ranked = ranking(db, c)
    for i, p in enumerate(ranked, start=1):
        p.rank = i
    schedule = settings.codewar_rewards if c.kind == CONTEST_CODEWAR else settings.exam_rewards
    scorers = [p for p in ranked if (p.score or 0) > 0]
    eligible = [p for p in scorers if not (c.kind == CONTEST_CODEWAR and p.user_id == c.creator_id)]
    pay = True
    if c.kind == CONTEST_CODEWAR and len(scorers) < settings.codewar_min_players:
        pay = False
    reason = "CODEWAR_REWARD" if c.kind == CONTEST_CODEWAR else "EXAM_REWARD"
    label = "Code War" if c.kind == CONTEST_CODEWAR else "Bài kiểm tra"
    for idx, p in enumerate(eligible[:len(schedule)]):
        amount = schedule[idx] if pay else 0
        if amount > 0:
            bcoins.change(db, p.user_id, amount, reason, "contest", c.id, f"Hạng {p.rank} · {c.title}")
            p.bcoins_awarded = amount
    c.finalized_at = utcnow()
    db.commit()
    link = f"/#thi-dau-{c.id}"
    for p in ranked:
        user = db.get(User, p.user_id)
        if not user:
            continue
        extra = f" Bạn được cộng {p.bcoins_awarded} Bcoins." if p.bcoins_awarded else ""
        if not pay and c.kind == CONTEST_CODEWAR and p in eligible[:10]:
            extra = f" Phòng có dưới {settings.codewar_min_players} người có điểm nên không trao Bcoins."
        notify(db, user, f"{label} “{c.title}” đã kết thúc", f"Bạn xếp hạng {p.rank}/{len(ranked)} với {p.score:g} điểm.{extra}",
               link, email=bool(p.bcoins_awarded))
    creator = db.get(User, c.creator_id)
    if creator and not any(p.user_id == creator.id for p in ranked):
        notify(db, creator, f"Phòng “{c.title}” đã chốt bảng xếp hạng", f"{len(ranked)} người tham gia.", link)


def finalize_due(db: Session) -> int:
    now = utcnow()
    due = db.scalars(select(Contest).where(Contest.finalized_at.is_(None), Contest.end_at <= now)).all()
    for c in due:
        try:
            finalize(db, c)
        except Exception:
            db.rollback()
            log.exception("Chốt phòng %s thất bại", c.id)
    return len(due)


def ensure_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def problem_public(prob: ContestProblem, with_tests: bool = False) -> dict:
    d = {"id": prob.id, "position": prob.position, "title": prob.title, "statement": prob.statement,
         "input_format": prob.input_format, "output_format": prob.output_format, "points": prob.points,
         "time_limit_ms": prob.time_limit_ms, "memory_mb": prob.memory_mb,
         "samples": [{"input": t.input, "output": t.expected_output} for t in prob.tests if t.is_sample]}
    if with_tests:
        d["tests"] = [{"id": t.id, "input": t.input, "expected_output": t.expected_output, "is_sample": t.is_sample,
                       "weight": t.weight} for t in prob.tests]
    return d
