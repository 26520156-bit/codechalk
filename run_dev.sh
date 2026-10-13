#!/usr/bin/env bash
# CodeChalk Platform — chạy thử trên Linux, macOS hoặc WSL (SQLite).   bash run_dev.sh
# Dùng thư mục .venv-linux riêng để không đụng .venv của Windows khi chạy trong WSL.
set -euo pipefail
cd "$(dirname "$0")"
VENV=.venv-linux
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" || { echo "Thiếu venv: chạy 'sudo apt install python3-venv python3-pip' rồi thử lại."; exit 1; }
fi
if [ ! -f "$VENV/.installed" ]; then
  "$VENV/bin/pip" install --upgrade pip
  "$VENV/bin/pip" install --prefer-binary -r requirements.txt && touch "$VENV/.installed"
fi
[ -f .env ] || "$VENV/bin/python" scripts/setup_env.py
[ -f .env ] || { echo "Chưa có .env"; exit 1; }
command -v g++ >/dev/null || echo "[Lưu ý] Chưa có g++: chạy 'sudo apt install g++' để chấm bài C++."
echo "Mở http://localhost:8000  (Ctrl+C để dừng)"
exec "$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
