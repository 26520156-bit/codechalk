"""Kiểm tra dữ liệu đầu vào (Pydantic) và chuyển đối tượng CSDL thành JSON trả về."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import ROLE_LABEL

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^(0|\+84)(3|5|7|8|9)\d{8}$")


def norm_email(v: str) -> str:
    v = (v or "").strip().lower()
    if len(v) > 254 or not EMAIL_RE.match(v):
        raise ValueError("Email không hợp lệ.")
    return v


def norm_phone(v: str) -> str:
    v = re.sub(r"[\s.-]", "", v or "")
    if not PHONE_RE.match(v):
        raise ValueError("Số điện thoại không hợp lệ (ví dụ 0912345678).")
    return v


def check_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Mật khẩu cần ít nhất 8 ký tự.")
    if len(v.encode("utf-8")) > 72:
        raise ValueError("Mật khẩu tối đa 72 byte.")
    return v


# ---------- Tài khoản ----------
class RegisterIn(BaseModel):
    email: str
    password: str
    phone: str
    full_name: str = Field(default="", max_length=120)

    @field_validator("email")
    @classmethod
    def v_e_email(cls, v):
        return norm_email(v)

    @field_validator("phone")
    @classmethod
    def v_p_phone(cls, v):
        return norm_phone(v)

    @field_validator("password")
    @classmethod
    def v_w_password(cls, v):
        return check_password(v)



class LoginIn(BaseModel):
    email: str
    password: str = Field(max_length=200)
    @field_validator("email")
    @classmethod
    def v_e_email(cls, v):
        return (v or "").strip().lower()



class ProfileIn(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = None
    @field_validator("phone")
    @classmethod
    def v_p_phone(cls, v):
        return v if v is None else norm_phone(v)



class PasswordIn(BaseModel):
    old_password: str
    new_password: str
    @field_validator("new_password")
    @classmethod
    def v_w_new_password(cls, v):
        return check_password(v)



class AdminUserIn(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = None
    email: Optional[str] = None
    role: Optional[Literal["STUDENT", "TEACHER"]] = None
    is_active: Optional[bool] = None
    @field_validator("phone")
    @classmethod
    def v_p_phone(cls, v):
        return v if v is None else norm_phone(v)

    @field_validator("email")
    @classmethod
    def v_e_email(cls, v):
        return v if v is None else norm_email(v)



# ---------- Gói dịch vụ ----------
class PlanIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=60)
    price_vnd: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    duration_days: Optional[int] = Field(default=None, ge=0, le=3650)
    description: Optional[str] = None
    features: Optional[list[str]] = None
    is_active: Optional[bool] = None


class OrderIn(BaseModel):
    plan_id: Literal["ON_THI", "LOP_HOC"]


class ReviewIn(BaseModel):
    note: str = Field(default="", max_length=500)


class GrantIn(BaseModel):
    plan_id: Literal["ON_THI", "LOP_HOC"]
    days: int = Field(default=30, ge=0, le=3650)   # 0 = vĩnh viễn


# ---------- Phòng thi ----------
class TestIn(BaseModel):
    input: str = Field(default="", max_length=2_000_000)
    expected_output: str = Field(default="", max_length=2_000_000)
    is_sample: bool = False
    weight: int = Field(default=1, ge=1, le=100)


class ProblemIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    statement: str = Field(min_length=1, max_length=50_000)
    input_format: str = Field(default="", max_length=5000)
    output_format: str = Field(default="", max_length=5000)
    points: int = Field(default=100, ge=1, le=1000)
    time_limit_ms: int = Field(default=2000, ge=200, le=10_000)
    memory_mb: int = Field(default=256, ge=16, le=1024)
    tests: list[TestIn] = Field(default_factory=list, max_length=100)


class ContestIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=20_000)
    start_at: datetime
    end_at: datetime
    duration_minutes: int = Field(ge=5, le=60 * 24 * 14)
    grading_mode: Literal["AI", "TESTS"] = "TESTS"
    languages: list[Literal["cpp", "python", "java", "javascript"]] = Field(default_factory=lambda: ["cpp", "python"])
    problems: list[ProblemIn] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _times(self):
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("Thời gian phải kèm múi giờ (ví dụ 2026-10-20T19:00:00+07:00).")
        if self.end_at <= self.start_at:
            raise ValueError("Giờ kết thúc phải sau giờ bắt đầu.")
        if not self.languages:
            raise ValueError("Cần ít nhất một ngôn ngữ.")
        return self


class ContestPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=160)
    description: Optional[str] = Field(default=None, max_length=20_000)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=5, le=60 * 24 * 14)
    grading_mode: Optional[Literal["AI", "TESTS"]] = None


class SubmitIn(BaseModel):
    language: Literal["cpp", "python", "java", "javascript"]
    code: str = Field(min_length=1, max_length=100_000)


class RunIn(SubmitIn):
    input: str = Field(default="", max_length=1_000_000)


# ---------- Lịch học ----------
class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    note: str = Field(default="", max_length=5000)
    kind: Literal["STUDY", "PRACTICE", "GOAL", "EXAM"] = "STUDY"
    start_at: datetime
    end_at: Optional[datetime] = None
    repeat: Literal["NONE", "DAILY", "WEEKLY"] = "NONE"
    remind_minutes: int = Field(default=15, ge=0, le=60 * 24 * 7)
    notify_inapp: bool = True
    notify_email: bool = True
    done: bool = False

    @model_validator(mode="after")
    def _tz(self):
        if self.start_at.tzinfo is None:
            raise ValueError("Thời gian phải kèm múi giờ.")
        if self.end_at is not None and self.end_at < self.start_at:
            raise ValueError("Giờ kết thúc phải sau giờ bắt đầu.")
        return self


# ---------- Shop ----------
class CashoutIn(BaseModel):
    bcoins: int
    method: Literal["QR", "BANK"]
    bank_account: str = Field(default="", max_length=40)
    bank_name: str = Field(default="", max_length=80)
    account_holder: str = Field(default="", max_length=120)

    @field_validator("bcoins")
    @classmethod
    def _tier(cls, v: int) -> int:
        if v not in range(100, 1001, 100):
            raise ValueError("Chỉ đổi theo các mốc 100, 200, …, 1000 Bcoins.")
        return v


# ---------- Forum ----------
class RoomIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=2000)
    kind: Literal["ROOM", "GROUP"] = "ROOM"


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


# ---------- AI ----------
class TutorIn(BaseModel):
    mode: Literal["HINT", "DEBUG", "EXPLAIN"] = "HINT"
    language: Literal["cpp", "python", "java", "javascript"] = "cpp"
    code: str = Field(default="", max_length=100_000)
    question: str = Field(default="", max_length=2000)
    verdict: str = Field(default="", max_length=20)
    error: str = Field(default="", max_length=20_000)


class CoachIn(BaseModel):
    mode: Literal["HINT", "SUGGEST", "DEBUG", "EXPLAIN", "FIX", "SOLUTION"] = "HINT"
    language: Literal["cpp", "python", "java", "javascript"] = "cpp"
    code: str = Field(default="", max_length=100_000)
    question: str = Field(default="", max_length=2000)
    verdict: str = Field(default="", max_length=20)
    error: str = Field(default="", max_length=20_000)


class AIConfigIn(BaseModel):
    provider: Literal["gemini", "anthropic", "openai", "ollama", "none"]
    api_key: Optional[str] = Field(default=None, max_length=400)     # None = giữ khoá đã lưu
    model: str = Field(default="", max_length=120)
    base_url: str = Field(default="", max_length=300)

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if v and not re.match(r"^https?://[^\s]+$", v):
            raise ValueError("Địa chỉ máy chủ AI phải bắt đầu bằng http:// hoặc https://")
        return v.rstrip("/")


# ---------- Chuyển đối tượng → JSON ----------
def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def user_out(u, private: bool = False) -> dict:
    d = {"id": u.id, "full_name": u.full_name or u.email.split("@")[0], "role": u.role, "role_label": ROLE_LABEL.get(u.role, u.role),
         "xp": u.xp, "bcoins": u.bcoins}
    if private:
        d.update({"email": u.email, "phone": u.phone, "is_active": u.is_active, "created_at": iso(u.created_at),
                  "last_login_at": iso(u.last_login_at)})
    return d


def vn_time(dt: datetime | None, fmt: str = "%H:%M %d/%m/%Y") -> str:
    """Hiển thị giờ Việt Nam (UTC+7) trong thông báo và email."""
    from datetime import timedelta, timezone
    return dt.astimezone(timezone(timedelta(hours=7))).strftime(fmt) if dt else ""
