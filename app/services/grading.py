"""Xử lý bài nộp ở nền: chấm theo test (Judge) hoặc AI CHẤM, rồi cập nhật điểm, XP, tiến độ."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from ..db import SessionLocal, utcnow
from ..models import (HELP_FIX, HELP_SOLUTION, MODE_AI, Challenge, ChallengeHelp, ChallengeProgress, Contest, ContestProblem,
                      Participant, Submission, User)
from . import ai, judge
from .contests import recompute_participant
from .realtime import hub

log = logging.getLogger("codechalk.grading")
_tasks: set[asyncio.Task] = set()
CONTEST_AC_XP = 20          # XP cho lần AC đầu tiên một bài trong phòng thi


def schedule(sub_id: int) -> None:
    t = asyncio.get_running_loop().create_task(_safe(sub_id))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def _safe(sub_id: int) -> None:
    try:
        await process(sub_id)
    except Exception as e:  # không để lỗi hạ tầng làm treo bài nộp
        log.exception("Chấm bài %s lỗi", sub_id)
        with SessionLocal() as db:
            s = db.get(Submission, sub_id)
            if s and s.status != "DONE":
                s.status, s.verdict, s.feedback = "ERROR", "SE", f"Lỗi hệ thống khi chấm: {e}"
                db.commit()


def _report(res: judge.JudgeResult) -> str:
    if res.verdict == "CE":
        return "Không biên dịch được:\n" + res.compile[:1500]
    lines = []
    for t in res.tests:
        lines.append(f"- Test mẫu {t['i'] + 1}: {t['v']} ({t.get('ms', 0)} ms)" + (f" · {t.get('why')}" if t.get("why") else ""))
    return "\n".join(lines) or "(không có test mẫu)"


def _statement(title: str, statement: str, inp: str, out: str) -> str:
    s = f"{title}\n{statement}"
    if inp:
        s += f"\nInput: {inp}"
    if out:
        s += f"\nOutput: {out}"
    return s


async def process(sub_id: int) -> None:
    with SessionLocal() as db:
        s = db.get(Submission, sub_id)
        if not s or s.status == "DONE":
            return
        s.status = "RUNNING"
        db.commit()
        if s.contest_id:
            prob = db.get(ContestProblem, s.problem_id)
            contest = db.get(Contest, s.contest_id)
            tests = [{"input": t.input, "expected": t.expected_output, "w": t.weight, "sample": t.is_sample} for t in prob.tests]
            tl, mem, mode = prob.time_limit_ms, prob.memory_mb, contest.grading_mode
            text = _statement(prob.title, prob.statement, prob.input_format, prob.output_format)
        else:
            ch = db.get(Challenge, s.challenge_id)
            tests = [{"input": t.input, "expected": t.expected_output, "w": 1, "sample": t.is_sample} for t in ch.tests]
            tl, mem = ch.time_limit_ms, ch.memory_mb
            mode = "TESTS" if ch.has_tests and tests else MODE_AI
            text = _statement(f"Bài {ch.id}: {ch.title}", ch.statement, ch.input_format, ch.output_format)
        lang, code = s.language, s.code

    details: dict = {"mode": mode}
    feedback, verdict, score, passed, total, ms = "", "", 0.0, 0, 0, 0
    if mode == MODE_AI:
        samples = [t for t in tests if t["sample"]] or tests[:3]
        rep = ""
        if samples:
            r = await judge.judge(lang, code, samples, tl, mem)
            rep = _report(r)
            details["samples"] = r.to_dict()
            passed, total, ms = r.passed, len(samples), r.max_ms
        try:
            g = await ai.grade(text, lang, code, rep)
            score, verdict = float(g["score"]), "AI"
            details["ai"] = g
            feedback = g.get("summary", "")
        except Exception as e:  # AI lỗi: báo rõ, không cho điểm bừa
            verdict, feedback = "SE", f"AI CHẤM tạm thời không dùng được: {e}"
    else:
        r = await judge.judge(lang, code, tests, tl, mem)
        wsum = sum(t["w"] for t in tests) or 1
        got = sum(tests[x["i"]]["w"] for x in r.tests if x.get("v") == "AC")
        score = round(got / wsum * 100, 2) if r.verdict != "CE" else 0.0
        verdict = r.verdict if r.verdict in ("AC", "CE", "SE") else ("PART" if r.passed else r.verdict)
        passed, total, ms = r.passed, len(tests), r.max_ms
        # Ẩn input/expected của test ẩn: chỉ trả trạng thái từng test
        details["tests"] = [{"i": x["i"], "v": x["v"], "ms": x.get("ms", 0), "why": x.get("why", ""),
                             "sample": tests[x["i"]]["sample"],
                             "stderr": x.get("stderr", "")[-1500:] if tests[x["i"]]["sample"] else ""} for x in r.tests]
        details["compile"] = r.compile
        if r.verdict == "SE":
            feedback = r.compile

    with SessionLocal() as db:
        s = db.get(Submission, sub_id)
        s.status = "DONE" if verdict != "SE" else "ERROR"
        s.verdict, s.score, s.passed, s.total, s.time_ms, s.details, s.feedback = verdict, score, passed, total, ms, details, feedback
        db.flush()   # để truy vấn tính điểm bên dưới thấy kết quả của bài vừa chấm
        user = db.get(User, s.user_id)
        if s.contest_id and s.status == "DONE":
            c = db.get(Contest, s.contest_id)
            p = db.scalar(select(Participant).where(Participant.contest_id == c.id, Participant.user_id == s.user_id))
            if p is not None and s.created_at <= p.deadline_at:
                recompute_participant(db, c, p, s.created_at)
            if verdict == "AC" and not db.scalar(select(Submission.id).where(
                    Submission.user_id == s.user_id, Submission.problem_id == s.problem_id,
                    Submission.verdict == "AC", Submission.id != s.id).limit(1)):
                user.xp += CONTEST_AC_XP
                details["xp_gained"] = CONTEST_AC_XP
                s.details = dict(details)
                flag_modified(s, "details")
        if s.challenge_id and s.status == "DONE":
            ch = db.get(Challenge, s.challenge_id)
            pr = db.scalar(select(ChallengeProgress).where(ChallengeProgress.user_id == s.user_id,
                                                           ChallengeProgress.challenge_id == ch.id))
            if pr is None:
                pr = ChallengeProgress(user_id=s.user_id, challenge_id=ch.id)
                db.add(pr)
            pr.attempts = (pr.attempts or 0) + 1
            pr.best_score = max(pr.best_score or 0, score)
            ok = verdict == "AC" or (verdict == "AI" and score >= 80 and details.get("ai", {}).get("correctness", 0) >= 80)
            if ok and pr.solved_at is None:
                pr.solved_at = utcnow()
                help_ = db.scalar(select(ChallengeHelp.level).where(ChallengeHelp.user_id == s.user_id,
                                                                     ChallengeHelp.challenge_id == ch.id))
                gain = 0 if help_ == HELP_SOLUTION else ch.xp // 2 if help_ == HELP_FIX else ch.xp
                user.xp += gain
                details["xp_gained"] = gain
                if help_:
                    details["xp_note"] = ("Đã xem code đáp án nên bài này không cộng XP." if help_ == HELP_SOLUTION
                                          else f"Đã dùng “Sửa lỗi giúp” nên chỉ cộng {gain}/{ch.xp} XP.")
                s.details = dict(details)
                flag_modified(s, "details")
        db.commit()
        hub.push_user(s.user_id, {"type": "submission", "id": s.id, "verdict": s.verdict, "score": s.score,
                                  "contest_id": s.contest_id, "challenge_id": s.challenge_id})


def requeue_stale() -> int:
    """Khởi động lại server: chấm tiếp các bài còn nằm trong hàng đợi."""
    with SessionLocal() as db:
        ids = db.scalars(select(Submission.id).where(Submission.status.in_(("QUEUED", "RUNNING")))).all()
    for i in ids:
        schedule(i)
    return len(ids)
