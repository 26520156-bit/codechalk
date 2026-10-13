"""CHALLENGE: lộ trình 1000 bài code từ dễ đến khó, chấm bằng test (nếu có) hoặc AI."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, optional_user
from ..models import HELP_FIX, HELP_SOLUTION, Challenge, ChallengeHelp, ChallengeProgress, ChallengeSolution, Submission, User
from ..schemas import CoachIn, RunIn, SubmitIn
from ..services import access, ai, coach, grading, judge
from .contests import submission_out

router = APIRouter(prefix="/api/challenges", tags=["Challenge"])
DIFF = {1: "Dễ", 2: "Cơ bản", 3: "Trung bình", 4: "Khá", 5: "Khó"}


def ch_out(c: Challenge, prog: ChallengeProgress | None = None, locked: bool = False, full: bool = False) -> dict:
    d = {"id": c.id, "chapter": c.chapter, "chapter_title": c.chapter_title, "section": c.section, "title": c.title,
         "difficulty": c.difficulty, "difficulty_label": DIFF.get(c.difficulty, ""), "xp": c.xp, "has_tests": c.has_tests,
         "grading": "TESTS" if c.has_tests else "AI", "locked": locked,
         "progress": None if not prog else {"best_score": prog.best_score, "attempts": prog.attempts, "solved": prog.solved_at is not None}}
    if full and not locked:
        d.update(statement=c.statement, input_format=c.input_format, output_format=c.output_format, samples=c.samples or [],
                 time_limit_ms=c.time_limit_ms, memory_mb=c.memory_mb)
    return d


@router.get("/chapters")
def chapters(user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Challenge.chapter, Challenge.chapter_title, func.count(), func.min(Challenge.id), func.max(Challenge.id),
                             func.sum(case((Challenge.has_tests.is_(True), 1), else_=0)))
                      .group_by(Challenge.chapter, Challenge.chapter_title).order_by(Challenge.chapter)).all()
    solved = {}
    if user:
        solved = dict(db.execute(select(Challenge.chapter, func.count()).join(ChallengeProgress, ChallengeProgress.challenge_id == Challenge.id)
                                 .where(ChallengeProgress.user_id == user.id, ChallengeProgress.solved_at.is_not(None))
                                 .group_by(Challenge.chapter)).all())
    return [{"chapter": ch, "title": t, "count": n, "from": a, "to": b, "with_tests": int(wt or 0), "solved": solved.get(ch, 0),
             "locked": not access.can_open_chapter(db, user, ch)} for ch, t, n, a, b, wt in rows]


@router.get("")
def list_challenges(chapter: int | None = None, q: str = "", status: str = "", page: int = 1, size: int = 50,
                    user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    stmt = select(Challenge)
    if chapter:
        stmt = stmt.where(Challenge.chapter == chapter)
    if q:
        like = f"%{q.strip().lower()}%"
        cond = [func.lower(Challenge.title).like(like), func.lower(Challenge.statement).like(like)]
        if q.strip().isdigit():
            cond.append(Challenge.id == int(q.strip()))
        stmt = stmt.where(or_(*cond))
    progs = {}
    if user:
        progs = {p.challenge_id: p for p in db.scalars(select(ChallengeProgress).where(ChallengeProgress.user_id == user.id)).all()}
    if status == "solved":
        stmt = stmt.where(Challenge.id.in_([k for k, p in progs.items() if p.solved_at]))
    elif status == "todo":
        stmt = stmt.where(Challenge.id.not_in([k for k, p in progs.items() if p.solved_at] or [-1]))
    elif status == "tests":
        stmt = stmt.where(Challenge.has_tests.is_(True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    size = max(10, min(size, 100))
    rows = db.scalars(stmt.order_by(Challenge.id).offset((max(page, 1) - 1) * size).limit(size)).all()
    return {"total": total, "page": page, "size": size,
            "items": [ch_out(c, progs.get(c.id), not access.can_open_chapter(db, user, c.chapter)) for c in rows]}


def _open(db: Session, cid: int, user: User | None) -> Challenge:
    c = db.get(Challenge, cid)
    if not c:
        raise HTTPException(404, "Không tìm thấy bài.")
    if not access.can_open_chapter(db, user, c.chapter):
        raise HTTPException(402, f"Chương {c.chapter} thuộc gói Ôn thi hoặc Lớp học. Gói Tự học mở chương 1 đến 5.")
    return c


@router.get("/{cid}")
def get_challenge(cid: int, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    c = db.get(Challenge, cid)
    if not c:
        raise HTTPException(404, "Không tìm thấy bài.")
    locked = not access.can_open_chapter(db, user, c.chapter)
    prog = db.scalar(select(ChallengeProgress).where(ChallengeProgress.user_id == user.id, ChallengeProgress.challenge_id == c.id)) if user else None
    d = ch_out(c, prog, locked, full=True)
    d["help"] = _help_level(db, user, c.id) if user else None
    d["prev"] = c.id - 1 if c.id > 1 else None
    d["next"] = c.id + 1 if db.get(Challenge, c.id + 1) else None
    return d


@router.post("/{cid}/run")
async def run(cid: int, body: RunIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _open(db, cid, user)
    if body.input.strip() or not c.samples:
        r = await judge.judge(body.language, body.code, [{"input": body.input}], c.time_limit_ms, c.memory_mb, run_only=True)
        return {"kind": "custom", **r.to_dict()}
    samples = [{"input": s.get("input", ""), "expected": s.get("output", ""), "show": True} for s in c.samples]
    r = await judge.judge(body.language, body.code, samples, c.time_limit_ms, c.memory_mb)
    out = r.to_dict()
    for x in out["tests"]:
        x["input"], x["expected"] = samples[x["i"]]["input"], samples[x["i"]]["expected"]
    return {"kind": "samples", **out}


@router.post("/{cid}/submit", status_code=202)
async def submit(cid: int, body: SubmitIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _open(db, cid, user)
    if not c.has_tests:
        access.take_ai_credit(db, user)      # AI CHẤM tính vào hạn mức AI trong ngày
    busy = db.scalar(select(func.count()).select_from(Submission).where(Submission.user_id == user.id,
                                                                         Submission.status.in_(("QUEUED", "RUNNING"))))
    if busy and busy >= 3:
        raise HTTPException(429, "Bạn đang có bài chờ chấm. Đợi kết quả rồi nộp tiếp.")
    s = Submission(user_id=user.id, challenge_id=c.id, language=body.language, code=body.code)
    db.add(s)
    db.commit()
    grading.schedule(s.id)
    return {"id": s.id, "status": s.status}


@router.get("/{cid}/submissions")
def my_submissions(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Submission).where(Submission.challenge_id == cid, Submission.user_id == user.id)
                      .order_by(Submission.id.desc()).limit(50)).all()
    return [submission_out(s, include_code=True) for s in rows]


# ---------- Trợ lý AI: gợi ý, sửa lỗi, đáp án ----------
XP_RULE = {None: "Giữ nguyên XP", HELP_FIX: "Đã dùng “Sửa lỗi giúp”: giải được bài này còn 50% XP",
           HELP_SOLUTION: "Đã xem đáp án: giải được bài này không cộng XP"}


def _help_level(db: Session, user: User, cid: int) -> str | None:
    h = db.scalar(select(ChallengeHelp).where(ChallengeHelp.user_id == user.id, ChallengeHelp.challenge_id == cid))
    return h.level if h else None


def _mark_help(db: Session, user: User, cid: int, level: str) -> str | None:
    """Ghi lại mức trợ giúp (chỉ khi chưa giải được bài). SOLUTION mạnh hơn FIX."""
    solved = db.scalar(select(ChallengeProgress.id).where(ChallengeProgress.user_id == user.id, ChallengeProgress.challenge_id == cid,
                                                          ChallengeProgress.solved_at.is_not(None)))
    h = db.scalar(select(ChallengeHelp).where(ChallengeHelp.user_id == user.id, ChallengeHelp.challenge_id == cid))
    if solved:
        return h.level if h else None
    if h is None:
        h = ChallengeHelp(user_id=user.id, challenge_id=cid, level=level)
        db.add(h)
    elif h.level != HELP_SOLUTION:
        h.level = level
    db.commit()
    return h.level


@router.post("/{cid}/ai")
async def assist(cid: int, body: CoachIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Trợ lý AI của bài: HINT gợi ý hướng · SUGGEST gợi ý code · DEBUG vì sao sai · EXPLAIN giải thích ·
    FIX sửa lỗi giúp (còn 50% XP) · SOLUTION code đáp án (không cộng XP). Code AI viết được chạy thử trên test của bài."""
    c = _open(db, cid, user)
    if body.mode in ("DEBUG", "EXPLAIN", "FIX") and len(body.code.strip()) < 15:
        raise HTTPException(400, "Bạn chưa viết code. Hãy dùng “Gợi ý hướng làm” hoặc “Gợi ý code” trước nhé.")
    if not ai.enabled():
        raise HTTPException(503, ai.NOT_CONFIGURED)
    cached = None
    if body.mode == "SOLUTION":
        cached = db.scalar(select(ChallengeSolution).where(ChallengeSolution.challenge_id == c.id,
                                                           ChallengeSolution.language == body.language))
        if cached and (cached.verified or not coach.tests_of(c)):
            level = _mark_help(db, user, c.id, HELP_SOLUTION)
            return {"mode": body.mode, "language": body.language, "text": cached.explanation, "code": cached.code, "cached": True,
                    "verify": {"ok": cached.verified, "passed": cached.passed, "total": cached.total, "verdict": "AC" if cached.verified else ""}
                    if cached.total else None,
                    "help": level, "xp_rule": XP_RULE[level], "used_today": access.ai_used_today(user), "quota": access.ai_quota(db, user)}
    used, limit = access.take_ai_credit(db, user)
    try:
        r = await coach.ask(body.mode, c, body.language, body.code, body.question, body.verdict, body.error)
    except ai.AIUnavailable as e:
        raise HTTPException(503, str(e)) from None
    level = _help_level(db, user, c.id)
    if body.mode in ("FIX", "SOLUTION") and r["code"]:
        level = _mark_help(db, user, c.id, HELP_FIX if body.mode == "FIX" else HELP_SOLUTION)
    v = r["verify"]
    if body.mode == "SOLUTION" and r["code"] and (v is None or v["ok"]):
        row = cached or ChallengeSolution(challenge_id=c.id, language=body.language)
        row.code, row.explanation, row.model = r["code"], r["text"], ai.model_name()
        row.verified, row.passed, row.total = bool(v and v["ok"]), (v or {}).get("passed", 0), (v or {}).get("total", 0)
        if cached is None:
            db.add(row)
        db.commit()
    return {"mode": body.mode, "language": body.language, "text": r["text"], "code": r["code"], "verify": v, "cached": False,
            "attempts": r["attempts"], "help": level, "xp_rule": XP_RULE[level], "used_today": used, "quota": limit}
