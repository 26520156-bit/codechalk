"""CODE WAR (ai cũng tạo được) và BÀI KIỂM TRA (chỉ GIÁO VIÊN/HOST tạo)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import current_user, optional_user
from ..models import (CONTEST_CODEWAR, CONTEST_EXAM, DONE, MODE_AI, ONGOING, ROLE_HOST, ROLE_TEACHER, UPCOMING, Contest,
                      ContestProblem, Participant, Submission, TestCase, User)
from ..schemas import ContestIn, ContestPatch, ProblemIn, RunIn, SubmitIn, TestIn, iso, user_out
from ..services import access, grading, judge
from ..services.contests import ensure_utc, participant_deadline, problem_public, ranking, state_of

router = APIRouter(prefix="/api/contests", tags=["Code War & Bài kiểm tra"])
KIND = {"codewar": CONTEST_CODEWAR, "exam": CONTEST_EXAM, CONTEST_CODEWAR: CONTEST_CODEWAR, CONTEST_EXAM: CONTEST_EXAM}


def _get(db: Session, cid: int) -> Contest:
    c = db.get(Contest, cid)
    if not c:
        raise HTTPException(404, "Không tìm thấy phòng.")
    return c


def _is_owner(c: Contest, u: User | None) -> bool:
    return bool(u and (u.id == c.creator_id or u.role == ROLE_HOST))


def _participant(db: Session, c: Contest, u: User | None) -> Participant | None:
    if not u:
        return None
    return db.scalar(select(Participant).where(Participant.contest_id == c.id, Participant.user_id == u.id))


def contest_out(db: Session, c: Contest, u: User | None, full: bool = False) -> dict:
    now = utcnow()
    st = state_of(c, now)
    part = _participant(db, c, u)
    n = db.scalar(select(func.count()).select_from(Participant).where(Participant.contest_id == c.id))
    d = {"id": c.id, "kind": c.kind, "title": c.title, "description": c.description, "state": st,
         "start_at": iso(c.start_at), "end_at": iso(c.end_at), "duration_minutes": c.duration_minutes,
         "grading_mode": c.grading_mode, "languages": c.languages, "creator": user_out(c.creator) if c.creator else None,
         "participants": n, "problem_count": len(c.problems), "finalized": c.finalized_at is not None,
         "is_owner": _is_owner(c, u),
         "me": None if not part else {"joined_at": iso(part.joined_at), "deadline_at": iso(part.deadline_at),
                                      "score": part.score, "rank": part.rank, "bcoins_awarded": part.bcoins_awarded,
                                      "time_left_s": max(0, int((part.deadline_at - now).total_seconds())) if st == ONGOING else 0}}
    if full:
        owner = _is_owner(c, u)
        can_see = owner or (part is not None and st != UPCOMING) or st == DONE
        d["problems"] = [problem_public(p, with_tests=owner) for p in c.problems] if can_see else []
    return d


@router.get("")
def list_contests(kind: str = "codewar", state: str = "", mine: bool = False, user: User | None = Depends(optional_user),
                  db: Session = Depends(get_db)):
    k = KIND.get(kind)
    if not k:
        raise HTTPException(400, "kind phải là codewar hoặc exam.")
    q = select(Contest).where(Contest.kind == k).order_by(Contest.start_at.desc()).limit(200)
    rows = db.scalars(q).all()
    out = [contest_out(db, c, user) for c in rows]
    if state:
        out = [x for x in out if x["state"] == state]
    if mine and user:
        out = [x for x in out if x["is_owner"] or x["me"]]
    order = {ONGOING: 0, UPCOMING: 1, DONE: 2}
    out.sort(key=lambda x: (order[x["state"]], x["start_at"] if x["state"] != DONE else ""))
    return out


@router.post("", status_code=201)
def create_contest(body: ContestIn, kind: str = "codewar", user: User = Depends(current_user), db: Session = Depends(get_db)):
    k = KIND.get(kind)
    if not k:
        raise HTTPException(400, "kind phải là codewar hoặc exam.")
    if k == CONTEST_EXAM and user.role not in (ROLE_TEACHER, ROLE_HOST):
        raise HTTPException(403, "Chỉ GIÁO VIÊN hoặc HOST được tạo Phòng Kiểm tra.")
    if body.grading_mode == MODE_AI and not access.can_use_ai_grading(db, user):
        raise HTTPException(403, "Chế độ AI CHẤM dành cho GIÁO VIÊN, HOST hoặc tài khoản gói Lớp học.")
    if ensure_utc(body.end_at) <= utcnow():
        raise HTTPException(400, "Giờ kết thúc đã qua.")
    c = Contest(kind=k, title=body.title.strip(), description=body.description, creator_id=user.id,
                start_at=ensure_utc(body.start_at), end_at=ensure_utc(body.end_at), duration_minutes=body.duration_minutes,
                grading_mode=body.grading_mode, languages=list(dict.fromkeys(body.languages)))
    db.add(c)
    db.flush()
    for i, p in enumerate(body.problems, start=1):
        _add_problem(db, c, p, i)
    db.commit()
    db.refresh(c)
    return contest_out(db, c, user, full=True)


def _add_problem(db: Session, c: Contest, p: ProblemIn, position: int) -> ContestProblem:
    if c.grading_mode == "TESTS" and not any(True for _ in p.tests):
        pass  # cho phép thêm test sau
    prob = ContestProblem(contest_id=c.id, position=position, title=p.title, statement=p.statement, input_format=p.input_format,
                          output_format=p.output_format, points=p.points, time_limit_ms=p.time_limit_ms, memory_mb=p.memory_mb)
    db.add(prob)
    db.flush()
    for j, t in enumerate(p.tests, start=1):
        db.add(TestCase(problem_id=prob.id, position=j, input=t.input, expected_output=t.expected_output,
                        is_sample=t.is_sample, weight=t.weight))
    return prob


def _owner_edit(c: Contest, u: User, db: Session) -> None:
    if not _is_owner(c, u):
        raise HTTPException(403, "Chỉ người tạo phòng (hoặc HOST) được sửa.")
    if state_of(c) == DONE:
        raise HTTPException(400, "Phòng đã kết thúc, không sửa được.")


@router.get("/{cid}")
def get_contest(cid: int, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    return contest_out(db, _get(db, cid), user, full=True)


@router.patch("/{cid}")
def patch_contest(cid: int, body: ContestPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid)
    _owner_edit(c, user, db)
    data = body.model_dump(exclude_none=True)
    if state_of(c) == ONGOING and ({"start_at", "duration_minutes", "grading_mode"} & data.keys()):
        raise HTTPException(400, "Phòng đang diễn ra: chỉ đổi được tên, mô tả và giờ kết thúc.")
    if data.get("grading_mode") == MODE_AI and not access.can_use_ai_grading(db, user):
        raise HTTPException(403, "Chế độ AI CHẤM dành cho GIÁO VIÊN, HOST hoặc gói Lớp học.")
    for k, v in data.items():
        setattr(c, k, ensure_utc(v) if k in ("start_at", "end_at") else v)
    if c.end_at <= c.start_at:
        raise HTTPException(400, "Giờ kết thúc phải sau giờ bắt đầu.")
    db.commit()
    return contest_out(db, c, user, full=True)


@router.delete("/{cid}")
def delete_contest(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid)
    if not _is_owner(c, user):
        raise HTTPException(403, "Chỉ người tạo phòng (hoặc HOST) được xoá.")
    if state_of(c) != UPCOMING and user.role != ROLE_HOST:
        raise HTTPException(400, "Chỉ xoá được phòng chưa bắt đầu.")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/{cid}/problems", status_code=201)
def add_problem(cid: int, body: ProblemIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid)
    _owner_edit(c, user, db)
    prob = _add_problem(db, c, body, len(c.problems) + 1)
    db.commit()
    db.refresh(prob)
    return problem_public(prob, with_tests=True)


@router.put("/{cid}/problems/{pid}")
def edit_problem(cid: int, pid: int, body: ProblemIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid)
    _owner_edit(c, user, db)
    prob = db.get(ContestProblem, pid)
    if not prob or prob.contest_id != c.id:
        raise HTTPException(404, "Không tìm thấy bài.")
    for k in ("title", "statement", "input_format", "output_format", "points", "time_limit_ms", "memory_mb"):
        setattr(prob, k, getattr(body, k))
    if body.tests:
        prob.tests.clear()
        db.flush()
        for j, t in enumerate(body.tests, start=1):
            prob.tests.append(TestCase(position=j, input=t.input, expected_output=t.expected_output, is_sample=t.is_sample, weight=t.weight))
    db.commit()
    db.refresh(prob)
    return problem_public(prob, with_tests=True)


@router.delete("/{cid}/problems/{pid}")
def delete_problem(cid: int, pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid)
    _owner_edit(c, user, db)
    prob = db.get(ContestProblem, pid)
    if not prob or prob.contest_id != c.id:
        raise HTTPException(404, "Không tìm thấy bài.")
    db.delete(prob)
    db.commit()
    return {"ok": True}


@router.post("/{cid}/problems/{pid}/tests", status_code=201)
def add_tests(cid: int, pid: int, body: list[TestIn], user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid)
    _owner_edit(c, user, db)
    prob = db.get(ContestProblem, pid)
    if not prob or prob.contest_id != c.id:
        raise HTTPException(404, "Không tìm thấy bài.")
    if len(prob.tests) + len(body) > 100:
        raise HTTPException(400, "Mỗi bài tối đa 100 test.")
    start = len(prob.tests)
    for j, t in enumerate(body, start=start + 1):
        prob.tests.append(TestCase(position=j, input=t.input, expected_output=t.expected_output, is_sample=t.is_sample, weight=t.weight))
    db.commit()
    db.refresh(prob)
    return problem_public(prob, with_tests=True)


@router.delete("/{cid}/problems/{pid}/tests/{tid}")
def delete_test(cid: int, pid: int, tid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid)
    _owner_edit(c, user, db)
    t = db.get(TestCase, tid)
    if not t or t.problem_id != pid:
        raise HTTPException(404, "Không tìm thấy test.")
    db.delete(t)
    db.commit()
    return {"ok": True}


@router.post("/{cid}/join")
def join(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid)
    st = state_of(c)
    if st == DONE:
        raise HTTPException(400, "Phòng đã kết thúc.")
    if c.kind == CONTEST_EXAM and c.creator_id == user.id:
        raise HTTPException(400, "Người tạo phòng kiểm tra không tham gia làm bài.")
    p = _participant(db, c, user)
    if p is None:
        now = utcnow()
        begin = max(now, c.start_at)
        p = Participant(contest_id=c.id, user_id=user.id, joined_at=begin, deadline_at=participant_deadline(c, begin))
        db.add(p)
        db.commit()
    return contest_out(db, c, user, full=True)


def _check_can_submit(db: Session, c: Contest, user: User, pid: int, language: str) -> tuple[ContestProblem, Participant]:
    if state_of(c) != ONGOING:
        raise HTTPException(400, "Phòng không trong thời gian làm bài.")
    p = _participant(db, c, user)
    if p is None:
        raise HTTPException(403, "Bạn cần bấm JOIN trước khi làm bài.")
    if utcnow() > p.deadline_at:
        raise HTTPException(400, "Đã hết thời gian làm bài của bạn.")
    prob = db.get(ContestProblem, pid)
    if not prob or prob.contest_id != c.id:
        raise HTTPException(404, "Không tìm thấy bài.")
    if language not in c.languages:
        raise HTTPException(400, "Phòng này không cho phép ngôn ngữ đó.")
    return prob, p


@router.post("/{cid}/problems/{pid}/run")
async def run(cid: int, pid: int, body: RunIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid)
    owner = _is_owner(c, user)
    prob = db.get(ContestProblem, pid)
    if not prob or prob.contest_id != c.id:
        raise HTTPException(404, "Không tìm thấy bài.")
    if not owner:
        _check_can_submit(db, c, user, pid, body.language)
    if body.input.strip():
        r = await judge.judge(body.language, body.code, [{"input": body.input}], prob.time_limit_ms, prob.memory_mb, run_only=True)
        return {"kind": "custom", **r.to_dict()}
    samples = [{"input": t.input, "expected": t.expected_output, "show": True} for t in prob.tests if t.is_sample]
    if not samples:
        raise HTTPException(400, "Bài chưa có test mẫu. Hãy nhập input để chạy thử.")
    r = await judge.judge(body.language, body.code, samples, prob.time_limit_ms, prob.memory_mb)
    out = r.to_dict()
    for x in out["tests"]:
        x["input"], x["expected"] = samples[x["i"]]["input"], samples[x["i"]]["expected"]
    return {"kind": "samples", **out}


@router.post("/{cid}/problems/{pid}/submit", status_code=202)
async def submit(cid: int, pid: int, body: SubmitIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid)
    prob, _ = _check_can_submit(db, c, user, pid, body.language)
    if c.grading_mode == "TESTS" and not prob.tests:
        raise HTTPException(400, "Bài chưa có bộ test, chưa nộp được.")
    recent = db.scalar(select(func.count()).select_from(Submission).where(
        Submission.user_id == user.id, Submission.status.in_(("QUEUED", "RUNNING"))))
    if recent and recent >= 3:
        raise HTTPException(429, "Bạn đang có bài chờ chấm. Đợi kết quả rồi nộp tiếp.")
    s = Submission(user_id=user.id, contest_id=c.id, problem_id=prob.id, language=body.language, code=body.code)
    db.add(s)
    db.commit()
    grading.schedule(s.id)
    return {"id": s.id, "status": s.status}


@router.get("/{cid}/leaderboard")
def leaderboard(cid: int, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    c = _get(db, cid)
    rows = ranking(db, c)
    out = []
    for i, p in enumerate(rows, start=1):
        elapsed = int((p.last_improve_at - p.joined_at).total_seconds()) if p.last_improve_at else None
        out.append({"rank": p.rank or i, "user": user_out(p.user), "score": p.score, "elapsed_s": elapsed,
                    "bcoins_awarded": p.bcoins_awarded, "is_me": bool(user and p.user_id == user.id)})
    return {"state": state_of(c), "finalized": c.finalized_at is not None, "rows": out}


@router.get("/{cid}/submissions")
def submissions(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get(db, cid)
    q = select(Submission).where(Submission.contest_id == c.id).order_by(Submission.id.desc()).limit(300)
    if not _is_owner(c, user):
        q = q.where(Submission.user_id == user.id)
    return [submission_out(s, include_code=False) for s in db.scalars(q).all()]


def submission_out(s: Submission, include_code: bool = True) -> dict:
    d = {"id": s.id, "user": user_out(s.user) if s.user else None, "contest_id": s.contest_id, "problem_id": s.problem_id,
         "challenge_id": s.challenge_id, "language": s.language, "status": s.status, "verdict": s.verdict, "score": s.score,
         "passed": s.passed, "total": s.total, "time_ms": s.time_ms, "feedback": s.feedback, "details": s.details,
         "created_at": iso(s.created_at)}
    if include_code:
        d["code"] = s.code
    return d


sub_router = APIRouter(prefix="/api/submissions", tags=["Bài nộp"])


@sub_router.get("/{sid}")
def get_submission(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(Submission, sid)
    if not s:
        raise HTTPException(404, "Không tìm thấy bài nộp.")
    if s.user_id != user.id and user.role != ROLE_HOST:
        c = db.get(Contest, s.contest_id) if s.contest_id else None
        if not (c and c.creator_id == user.id):
            raise HTTPException(403, "Bạn không xem được bài nộp này.")
    return submission_out(s)
