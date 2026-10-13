"""Nạp lại ngân hàng bài Challenge từ data/challenges.json (cập nhật đề và bộ test).

    python scripts/load_challenges.py              # nạp file mặc định
    python scripts/load_challenges.py path/to.json # nạp file khác
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.seed import seed_challenges  # noqa: E402


def main() -> None:
    path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        n = seed_challenges(db, path=path, force=True)
    print(f"Đã nạp/cập nhật {n} bài Challenge.")


if __name__ == "__main__":
    main()
