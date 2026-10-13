#!/usr/bin/env bash
# Cập nhật mã nguồn mới (giữ nguyên .env và dữ liệu), dựng lại và khởi động.
#   sudo bash /opt/codechalk/deploy/update.sh ~/codechalk.tgz
set -euo pipefail
ARCHIVE="${1:?Cách dùng: sudo bash deploy/update.sh codechalk.tgz}"
ARCHIVE="$(readlink -f "$ARCHIVE")"
cd "$(dirname "$0")/.."
bash deploy/backup.sh || echo "    (Không sao lưu được trước khi cập nhật, vẫn tiếp tục)"
tar -xzf "$ARCHIVE" -C . --strip-components=1
find . -name '*.sh' -exec sed -i 's/\r$//' {} + -exec chmod +x {} +
docker compose --profile vps up -d --build
docker image prune -f >/dev/null 2>&1 || true
echo "    Đã cập nhật. Kiểm tra: curl -s http://127.0.0.1:8000/api/health"
