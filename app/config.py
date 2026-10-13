"""Cấu hình đọc từ biến môi trường (hoặc file .env ở thư mục gốc dự án)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Đọc file .env đơn giản (KEY=VALUE), không ghi đè biến đã có sẵn."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ.setdefault(key, val)


_load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _list(name: str, default: str) -> list[int]:
    return [int(x) for x in os.getenv(name, default).split(",") if x.strip()]


@dataclass
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'codechalk.db').as_posix()}")
    jwt_secret: str = os.getenv("JWT_SECRET", "doi-chuoi-nay-trong-file-.env")
    jwt_days: int = _int("JWT_DAYS", 7)
    cors_origins: list[str] = field(default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()])

    # Tài khoản HOST (Super Admin) được tạo khi khởi động nếu chưa có
    host_email: str = os.getenv("HOST_EMAIL", "")
    host_password: str = os.getenv("HOST_PASSWORD", "")
    host_phone: str = os.getenv("HOST_PHONE", "")
    host_name: str = os.getenv("HOST_NAME", "HOST")

    # Thanh toán VietQR (tài khoản nhận tiền của HOST)
    bank_bin: str = os.getenv("BANK_BIN", "970415")            # VietinBank
    bank_name: str = os.getenv("BANK_NAME", "VietinBank")
    bank_account: str = os.getenv("BANK_ACCOUNT", "")
    bank_holder: str = os.getenv("BANK_HOLDER", "")

    # Chấm bài: local | docker | judge0
    judge_mode: str = os.getenv("JUDGE_MODE", "local")
    judge_docker_image: str = os.getenv("JUDGE_DOCKER_IMAGE", "codechalk-judge:latest")
    judge0_url: str = os.getenv("JUDGE0_URL", "http://localhost:2358")
    judge0_token: str = os.getenv("JUDGE0_TOKEN", "")
    judge_max_parallel: int = _int("JUDGE_MAX_PARALLEL", 2)
    judge_work_dir: str = os.getenv("JUDGE_WORK_DIR", "")      # thư mục tạm chứa bài nộp đang chấm
    # Khi máy chủ cũng chạy trong Docker: tên volume chứa JUDGE_WORK_DIR, để container chấm chỉ gắn đúng thư mục của một bài
    judge_docker_volume: str = os.getenv("JUDGE_DOCKER_VOLUME", "")

    # AI: gemini | anthropic | openai | none
    ai_provider: str = os.getenv("AI_PROVIDER", "none")
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    ai_model: str = os.getenv("AI_MODEL", "")
    ai_base_url: str = os.getenv("AI_BASE_URL", "")

    # Email (Gmail SMTP: smtp.gmail.com:587 + App Password)
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = _int("SMTP_PORT", 587)
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")
    smtp_tls: bool = _bool("SMTP_TLS", True)

    # Bcoins
    bcoin_rate_vnd: int = _int("BCOIN_RATE_VND", 100)          # 1 Bcoin = 100 đ  (100 Bcoins = 10.000 đ)
    codewar_rewards: list[int] = field(default_factory=lambda: _list("CODEWAR_REWARDS", "10,9,8,7,6,5,4,3,2,1"))
    exam_rewards: list[int] = field(default_factory=lambda: _list("EXAM_REWARDS", "10,9,8,7,6,5,4,3,2,1"))
    codewar_min_players: int = _int("CODEWAR_MIN_PLAYERS", 3)  # phòng ít người hơn thì không trả Bcoins

    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", str(ROOT / "data" / "uploads")))
    max_upload_mb: int = _int("MAX_UPLOAD_MB", 25)
    web_dir: Path = Path(os.getenv("WEB_DIR", str(ROOT / "web")))
    scheduler_seconds: int = _int("SCHEDULER_SECONDS", 20)
    public_url: str = os.getenv("PUBLIC_URL", "http://localhost:8000")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
