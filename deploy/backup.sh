#!/usr/bin/env bash
# Sao lưu CSDL + tệp tải lên vào /opt/codechalk/backups (giữ 14 ngày). Cron gọi mỗi ngày, chạy tay cũng được.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups && chmod 700 backups
TS="$(date +%F_%H%M)"
docker compose exec -T db pg_dump -U codechalk --clean --if-exists --no-owner codechalk | gzip > "backups/db_${TS}.sql.gz"
docker compose exec -T app tar -czf - -C /data/uploads . > "backups/uploads_${TS}.tgz"
find backups -type f -mtime +14 -delete
echo "$(date '+%F %T') Đã sao lưu: backups/db_${TS}.sql.gz, backups/uploads_${TS}.tgz"
