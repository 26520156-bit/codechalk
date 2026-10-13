"""Chuyển toàn bộ dữ liệu từ bản chạy thử (SQLite, run_dev.bat) sang PostgreSQL (docker compose).

Chép mọi bảng (tài khoản, gói, phòng thi, bài nộp, Bcoins, forum, cấu hình AI…) và các tệp đã tải lên.
Dữ liệu đang có trong PostgreSQL sẽ bị thay bằng dữ liệu từ SQLite.

Trên Windows: chạy docker_import_sqlite.bat. Hoặc:
    docker compose stop app
    docker compose run --rm -v "%cd%\\data:/import:ro" app python scripts/sqlite_to_postgres.py /import/codechalk.db /import/uploads
    docker compose start app
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import Integer, create_engine, func, inspect, select, text  # noqa: E402

from app import models  # noqa: E402,F401  (đăng ký các bảng)
from app.config import settings  # noqa: E402
from app.db import Base, engine as dst  # noqa: E402

BATCH = 500


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src_path = Path(sys.argv[1])
    up_src = Path(sys.argv[2]) if len(sys.argv) > 2 else src_path.parent / "uploads"
    if not src_path.exists():
        sys.exit(f"Không thấy tệp {src_path}")
    if dst.dialect.name == "sqlite":
        sys.exit("DATABASE_URL đang trỏ tới SQLite. Chạy lệnh này trong container app của docker compose.")

    src = create_engine(f"sqlite:///{src_path.as_posix()}")
    src_cols = {t: {c["name"] for c in inspect(src).get_columns(t)} for t in inspect(src).get_table_names()}
    Base.metadata.create_all(dst)
    tables = Base.metadata.sorted_tables
    total = 0
    with dst.begin() as dc, src.connect() as sc:
        for t in reversed(tables):
            dc.execute(t.delete())
        for t in tables:
            if t.name not in src_cols:
                continue
            cols = [c for c in t.columns if c.name in src_cols[t.name]]
            result = sc.execute(select(*cols))
            n = 0
            while True:
                rows = result.fetchmany(BATCH)
                if not rows:
                    break
                dc.execute(t.insert(), [dict(r._mapping) for r in rows])
                n += len(rows)
            total += n
            print(f"  {t.name:<22} {n:>7} dòng")
        # Đặt lại bộ đếm id để bản ghi mới không trùng id đã chép
        for t in tables:
            for c in t.primary_key.columns:
                if isinstance(c.type, Integer):
                    dc.execute(text(f"SELECT setval(pg_get_serial_sequence('{t.name}', '{c.name}'), "
                                    f"COALESCE((SELECT MAX({c.name}) FROM {t.name}), 0) + 1, false)"))
    print(f"Đã chép {total} dòng sang PostgreSQL.")

    if up_src.is_dir():
        dest = Path(settings.upload_dir)
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(up_src, dest, dirs_exist_ok=True)
        print(f"Đã chép {sum(1 for p in up_src.rglob('*') if p.is_file())} tệp tải lên vào {dest}.")
    with dst.connect() as dc:
        users = dc.scalar(select(func.count()).select_from(models.User))
    print(f"Xong. PostgreSQL hiện có {users} tài khoản. Khởi động lại app: docker compose start app")


if __name__ == "__main__":
    main()
