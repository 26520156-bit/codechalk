#!/usr/bin/env bash
# Nạp lại dữ liệu từ bản sao lưu (thay toàn bộ dữ liệu hiện tại).
#   bash deploy/restore.sh backups/db_XXXX.sql.gz [backups/uploads_XXXX.tgz]
#   (chấp nhận cả tệp .sql chưa nén)
set -euo pipefail
DUMP="${1:?Cách dùng: bash deploy/restore.sh <db.sql|db.sql.gz> [uploads.tgz]}"
UPLOADS="${2:-}"
DUMP="$(readlink -f "$DUMP")"; [ -n "$UPLOADS" ] && UPLOADS="$(readlink -f "$UPLOADS")"
cd "$(dirname "$0")/.."
docker compose stop app
if [[ "$DUMP" == *.gz ]]; then gunzip -c "$DUMP"; else cat "$DUMP"; fi \
  | sed 's/\r$//' | docker compose exec -T db psql -q -U codechalk -d codechalk -v ON_ERROR_STOP=1 >/dev/null
echo "    Đã nạp cơ sở dữ liệu."
if [ -n "$UPLOADS" ] && [ -s "$UPLOADS" ]; then
  docker compose run --rm --no-deps -v "$UPLOADS:/in.tgz:ro" --entrypoint sh app -c "tar -xzf /in.tgz -C /data/uploads"
  echo "    Đã nạp tệp tải lên."
fi
docker compose start app
echo "    Xong. Máy chủ đã khởi động lại với dữ liệu mới."
