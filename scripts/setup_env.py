"""Tạo file .env lần đầu cho CodeChalk Platform.

Hỏi thông tin tài khoản HOST và tài khoản nhận tiền VietQR, tự sinh JWT_SECRET và mật khẩu PostgreSQL.
Mật khẩu HOST chỉ được ghi vào .env trên máy bạn (server băm bcrypt khi tạo tài khoản).

    python scripts/setup_env.py           # tạo .env nếu chưa có
    python scripts/setup_env.py --force   # tạo lại (ghi đè .env cũ)
"""
from __future__ import annotations

import getpass
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE, TARGET = ROOT / ".env.example", ROOT / ".env"

# Giá trị gợi ý sẵn (Enter để giữ nguyên)
DEFAULTS = {
    "HOST_EMAIL": "email-cua-ban@example.com",
    "HOST_PHONE": "0900000000",
    "HOST_NAME": "HOST",
    "BANK_BIN": "970415",
    "BANK_NAME": "VietinBank",
    "BANK_ACCOUNT": "",
    "BANK_HOLDER": "",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^(0|\+84)(3|5|7|8|9)\d{8}$")


def ask(label: str, default: str, check=None, msg: str = "") -> str:
    while True:
        v = input(f"{label} [{default}]: ").strip() or default
        if check is None or check(v):
            return v
        print("  ", msg or "Giá trị không hợp lệ, nhập lại.")


def ask_password() -> str:
    while True:
        p1 = getpass.getpass("Mật khẩu HOST (8–72 ký tự, không hiện khi gõ): ")
        if not 8 <= len(p1.encode("utf-8")) <= 72:
            print("   Mật khẩu cần từ 8 đến 72 byte.")
            continue
        if '"' in p1:
            print("   Không dùng dấu nháy kép trong mật khẩu.")
            continue
        if getpass.getpass("Nhập lại mật khẩu HOST: ") != p1:
            print("   Hai lần nhập không khớp.")
            continue
        return p1


def set_key(text: str, key: str, value: str) -> str:
    if any(c in value for c in "\r\n"):
        raise ValueError(key)
    if " " in value or "#" in value:
        value = '"' + value.replace('"', "") + '"'
    pat = re.compile(rf"^#?\s*{re.escape(key)}=.*$", re.M)
    return pat.sub(lambda _: f"{key}={value}", text, count=1) if pat.search(text) else text + f"\n{key}={value}\n"


def main() -> None:
    if TARGET.exists() and "--force" not in sys.argv:
        print(".env đã có sẵn. Chạy với --force nếu muốn tạo lại.")
        return
    if not sys.stdin.isatty():
        sys.exit("Cần chạy trong cửa sổ dòng lệnh để nhập thông tin (hoặc chép .env.example thành .env rồi sửa tay).")
    print("=== Thiết lập CodeChalk Platform: tài khoản HOST và tài khoản nhận tiền ===")
    vals = {
        "HOST_EMAIL": ask("Email HOST", DEFAULTS["HOST_EMAIL"], EMAIL_RE.match, "Email không hợp lệ."),
        "HOST_PASSWORD": ask_password(),
        "HOST_PHONE": ask("Số điện thoại HOST", DEFAULTS["HOST_PHONE"], PHONE_RE.match, "Số điện thoại Việt Nam 10 số, vd 0912345678."),
        "HOST_NAME": ask("Tên hiển thị HOST", DEFAULTS["HOST_NAME"]),
        "BANK_BIN": ask("Mã BIN ngân hàng (VietinBank 970415)", DEFAULTS["BANK_BIN"], lambda v: v.isdigit() and len(v) == 6, "BIN gồm 6 chữ số."),
        "BANK_NAME": ask("Tên ngân hàng", DEFAULTS["BANK_NAME"]),
        "BANK_ACCOUNT": ask("Số tài khoản nhận tiền", DEFAULTS["BANK_ACCOUNT"], lambda v: v.isdigit() and 6 <= len(v) <= 19, "Chỉ gồm chữ số."),
        "BANK_HOLDER": ask("Tên chủ tài khoản (in hoa, không dấu)", DEFAULTS["BANK_HOLDER"]).upper(),
        "JWT_SECRET": secrets.token_urlsafe(48),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(18),
    }
    text = EXAMPLE.read_text(encoding="utf-8")
    for k, v in vals.items():
        text = set_key(text, k, v)
    TARGET.write_text(text, encoding="utf-8")
    print(f"\nĐã tạo {TARGET}. Khởi động server rồi đăng nhập bằng {vals['HOST_EMAIL']}.")


if __name__ == "__main__":
    main()
