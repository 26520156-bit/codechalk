import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(ROOT / "data" / "test.db"))
os.environ["HOST_EMAIL"] = "host@test.vn"
os.environ["HOST_PASSWORD"] = "host-pass-123"
os.environ["HOST_PHONE"] = "0912345678"
os.environ["BANK_ACCOUNT"] = "0123456789"
os.environ["BANK_HOLDER"] = "NGUYEN VAN A"
os.environ["UPLOAD_DIR"] = str(ROOT / "data" / "test_uploads")
os.environ["JWT_SECRET"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SCHEDULER_SECONDS"] = "3600"
os.environ["AI_PROVIDER"] = "none"


@pytest.fixture(scope="session")
def client():
    url = os.environ["DATABASE_URL"]
    if url.startswith("sqlite"):
        p = Path(url.replace("sqlite:///", ""))
        p.unlink(missing_ok=True)
    from app.db import Base, engine
    if not url.startswith("sqlite"):
        Base.metadata.drop_all(engine)
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
