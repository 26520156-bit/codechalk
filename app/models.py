"""Mô hình dữ liệu (SQLAlchemy 2.0). Xem sơ đồ quan hệ trong docs/ARCHITECTURE.md."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
                        TypeDecorator, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow


class UTCDateTime(TypeDecorator):
    """Luôn lưu và trả về datetime có múi giờ UTC (SQLite không tự giữ múi giờ)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


# ---------- Vai trò, trạng thái ----------
ROLE_STUDENT, ROLE_TEACHER, ROLE_HOST = "STUDENT", "TEACHER", "HOST"
ROLE_LABEL = {ROLE_STUDENT: "SINH VIÊN", ROLE_TEACHER: "GIÁO VIÊN", ROLE_HOST: "HOST"}

PLAN_SELF, PLAN_EXAM, PLAN_CLASS = "TU_HOC", "ON_THI", "LOP_HOC"

PENDING, APPROVED, REJECTED, CANCELLED, COMPLETED = "PENDING", "APPROVED", "REJECTED", "CANCELLED", "COMPLETED"

CONTEST_CODEWAR, CONTEST_EXAM = "CODEWAR", "EXAM"
MODE_AI, MODE_TESTS = "AI", "TESTS"
UPCOMING, ONGOING, DONE = "UPCOMING", "ONGOING", "DONE"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(20))
    full_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(16), default=ROLE_STUDENT, index=True)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    bcoins: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (CheckConstraint("bcoins >= 0", name="ck_users_bcoins_nonneg"),
                      CheckConstraint("role in ('STUDENT','TEACHER','HOST')", name="ck_users_role"))


# ---------- Gói dịch vụ & thanh toán ----------
class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)        # TU_HOC / ON_THI / LOP_HOC
    name: Mapped[str] = mapped_column(String(60))
    price_vnd: Mapped[int] = mapped_column(Integer, default=0)
    duration_days: Mapped[int] = mapped_column(Integer, default=30)      # 0 = vĩnh viễn
    description: Mapped[str] = mapped_column(Text, default="")
    features: Mapped[list[str]] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PaymentOrder(Base):
    __tablename__ = "payment_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"))
    amount_vnd: Mapped[int] = mapped_column(Integer)
    transfer_code: Mapped[str] = mapped_column(String(64), index=True)   # SUB_[USER_ID]_[TIER_ID]
    status: Mapped[str] = mapped_column(String(12), default=PENDING, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    plan: Mapped[Plan] = relationship()


class UserPlan(Base):
    """Quyền dùng một phiên bản (Tự học / Ôn thi / Lớp học) của người dùng."""
    __tablename__ = "user_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    granted_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("payment_orders.id"), nullable=True)
    __table_args__ = (UniqueConstraint("user_id", "plan_id", name="uq_user_plan"),)


# ---------- Phòng thi đấu (Code War) & Phòng kiểm tra (Exam) ----------
class Contest(Base):
    __tablename__ = "contests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)            # CODEWAR / EXAM
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    grading_mode: Mapped[str] = mapped_column(String(8), default=MODE_TESTS)  # AI / TESTS
    languages: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["cpp", "python"])
    finalized_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    creator: Mapped[User] = relationship()
    problems: Mapped[list["ContestProblem"]] = relationship(back_populates="contest", cascade="all, delete-orphan",
                                                            order_by="ContestProblem.position")
    __table_args__ = (CheckConstraint("end_at > start_at", name="ck_contest_time"),)


class ContestProblem(Base):
    __tablename__ = "contest_problems"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(160))
    statement: Mapped[str] = mapped_column(Text)
    input_format: Mapped[str] = mapped_column(Text, default="")
    output_format: Mapped[str] = mapped_column(Text, default="")
    points: Mapped[int] = mapped_column(Integer, default=100)
    time_limit_ms: Mapped[int] = mapped_column(Integer, default=2000)
    memory_mb: Mapped[int] = mapped_column(Integer, default=256)
    contest: Mapped[Contest] = relationship(back_populates="problems")
    tests: Mapped[list["TestCase"]] = relationship(back_populates="problem", cascade="all, delete-orphan",
                                                   order_by="TestCase.position")


class TestCase(Base):
    __tablename__ = "test_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("contest_problems.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    input: Mapped[str] = mapped_column(Text, default="")
    expected_output: Mapped[str] = mapped_column(Text, default="")
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    problem: Mapped[ContestProblem] = relationship(back_populates="tests")


class Participant(Base):
    __tablename__ = "participants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    deadline_at: Mapped[datetime] = mapped_column(UTCDateTime)          # min(vào phòng + thời lượng, giờ kết thúc)
    score: Mapped[float] = mapped_column(default=0.0)
    last_improve_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bcoins_awarded: Mapped[int] = mapped_column(Integer, default=0)
    user: Mapped[User] = relationship()
    __table_args__ = (UniqueConstraint("contest_id", "user_id", name="uq_participant"),)


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    contest_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"), nullable=True, index=True)
    problem_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contest_problems.id", ondelete="CASCADE"), nullable=True)
    challenge_id: Mapped[Optional[int]] = mapped_column(ForeignKey("challenges.id", ondelete="CASCADE"), nullable=True, index=True)
    language: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="QUEUED")    # QUEUED/RUNNING/DONE/ERROR
    verdict: Mapped[str] = mapped_column(String(8), default="")         # AC/WA/TLE/RE/CE/MLE/PART/AI
    score: Mapped[float] = mapped_column(default=0.0)                   # thang 0..100 của bài
    passed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    time_ms: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[Any] = mapped_column(JSON, default=dict)
    feedback: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    user: Mapped[User] = relationship()


# ---------- Bcoins ----------
class BcoinTransaction(Base):
    __tablename__ = "bcoin_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[int] = mapped_column(Integer)                        # + cộng, - trừ
    balance_after: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(24))                     # CODEWAR_REWARD/EXAM_REWARD/CASHOUT/REFUND/ADJUST
    ref_type: Mapped[str] = mapped_column(String(24), default="")
    ref_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (Index("ix_bcoin_ref", "ref_type", "ref_id", "user_id"),)


class CashoutRequest(Base):
    __tablename__ = "cashout_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    bcoins: Mapped[int] = mapped_column(Integer)
    amount_vnd: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(8))                     # QR / BANK
    qr_image: Mapped[str] = mapped_column(String(255), default="")      # đường dẫn tệp đã lưu
    bank_account: Mapped[str] = mapped_column(String(40), default="")
    bank_name: Mapped[str] = mapped_column(String(80), default="")
    account_holder: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(12), default=PENDING, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    processed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    user: Mapped[User] = relationship(foreign_keys=[user_id])


# ---------- Thời khoá biểu & thông báo ----------
class StudyEvent(Base):
    __tablename__ = "study_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    note: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(16), default="STUDY")      # STUDY / PRACTICE / GOAL / EXAM
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    repeat: Mapped[str] = mapped_column(String(8), default="NONE")      # NONE / DAILY / WEEKLY
    remind_minutes: Mapped[int] = mapped_column(Integer, default=15)
    notify_inapp: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)
    next_remind_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True, index=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(255), default="")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---------- Kho tài liệu ----------
class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(60), default="Khác", index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    uploader: Mapped[User] = relationship()


# ---------- Forum: nhóm & phòng chat ----------
class ChatRoom(Base):
    __tablename__ = "chat_rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    avatar: Mapped[str] = mapped_column(String(255), default="")
    kind: Mapped[str] = mapped_column(String(8), default="ROOM")        # ROOM (phòng chủ đề) / GROUP (cộng đồng)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RoomMember(Base):
    __tablename__ = "room_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("chat_rooms.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(8), default="MEMBER")      # OWNER / MEMBER
    last_read_id: Mapped[int] = mapped_column(Integer, default=0)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    user: Mapped[User] = relationship()
    __table_args__ = (UniqueConstraint("room_id", "user_id", name="uq_room_member"),)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("chat_rooms.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text, default="")
    attachment: Mapped[str] = mapped_column(String(255), default="")
    attachment_name: Mapped[str] = mapped_column(String(255), default="")
    attachment_mime: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    user: Mapped[User] = relationship()


# ---------- Challenge: 1000 bài code ----------
class Challenge(Base):
    __tablename__ = "challenges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)          # số thứ tự trong bộ 1000 bài
    chapter: Mapped[int] = mapped_column(Integer, index=True)
    chapter_title: Mapped[str] = mapped_column(String(120))
    section: Mapped[str] = mapped_column(String(160), default="")
    title: Mapped[str] = mapped_column(String(200))
    statement: Mapped[str] = mapped_column(Text)
    input_format: Mapped[str] = mapped_column(Text, default="")
    output_format: Mapped[str] = mapped_column(Text, default="")
    samples: Mapped[list[dict]] = mapped_column(JSON, default=list)
    difficulty: Mapped[int] = mapped_column(Integer, default=1)        # 1 dễ … 5 khó
    time_limit_ms: Mapped[int] = mapped_column(Integer, default=1000)
    memory_mb: Mapped[int] = mapped_column(Integer, default=256)
    xp: Mapped[int] = mapped_column(Integer, default=10)
    has_tests: Mapped[bool] = mapped_column(Boolean, default=False)
    tests: Mapped[list["ChallengeTest"]] = relationship(cascade="all, delete-orphan", order_by="ChallengeTest.position")


class ChallengeTest(Base):
    __tablename__ = "challenge_tests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    input: Mapped[str] = mapped_column(Text, default="")
    expected_output: Mapped[str] = mapped_column(Text, default="")
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)


class ChallengeProgress(Base):
    __tablename__ = "challenge_progress"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id", ondelete="CASCADE"), index=True)
    best_score: Mapped[float] = mapped_column(default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    solved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (UniqueConstraint("user_id", "challenge_id", name="uq_challenge_progress"),)


# ---------- Cấu hình chỉnh từ giao diện HOST (ghi đè .env) ----------
class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


# ---------- Trợ lý AI cho Challenge ----------
HELP_FIX, HELP_SOLUTION = "FIX", "SOLUTION"


class ChallengeSolution(Base):
    """Code đáp án do AI viết, đã chạy thử trên bộ test (nếu bài có test). Dùng lại cho mọi người, không tốn lượt AI."""
    __tablename__ = "challenge_solutions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id", ondelete="CASCADE"), index=True)
    language: Mapped[str] = mapped_column(String(12))
    code: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("challenge_id", "language", name="uq_challenge_solution"),)


class ChallengeHelp(Base):
    """Mức trợ giúp người học đã dùng trước khi giải được bài: FIX (còn 50% XP) hoặc SOLUTION (không cộng XP)."""
    __tablename__ = "challenge_help"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "challenge_id", name="uq_challenge_help"),)
