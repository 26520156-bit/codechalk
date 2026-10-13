#!/usr/bin/env bash
# =============================================================================
#  Cài CodeChalk lên VPS Ubuntu 22.04 / 24.04 (x86_64 hoặc ARM), chạy bằng root.
#
#    sudo bash setup_vps.sh codechalk.tgz [codechalk_db.sql] [codechalk_uploads.tgz]
#
#  Việc script làm: cập nhật hệ thống, tường lửa (chỉ mở 22/80/443), fail2ban,
#  swap, cài Docker, giải nén mã nguồn vào /opt/codechalk, tạo .env, hỏi tên miền,
#  khởi động (PostgreSQL + máy chủ + máy chấm + Caddy HTTPS), nạp dữ liệu cũ nếu có,
#  đặt lịch sao lưu hằng ngày. Chạy lại nhiều lần vẫn an toàn.
# =============================================================================
set -euo pipefail

ARCHIVE="${1:-}"
DB_DUMP="${2:-}"
UPLOADS="${3:-}"
APP_DIR=/opt/codechalk

trap 'ERR_LINE=$LINENO' ERR
trap 'rc=$?; [ $rc -ne 0 ] && printf "\n\033[1;31m    Script dừng ở dòng %s (mã lỗi %s). Chụp màn hình gửi lại để được hỗ trợ.\033[0m\n" "${ERR_LINE:-?}" "$rc"' EXIT
say()  { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m    %s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m    %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Hãy chạy bằng quyền root:  sudo bash $0 $*"; exit 1; }
[ -n "$ARCHIVE" ] && [ -f "$ARCHIVE" ] || { echo "Thiếu tệp mã nguồn. Cách dùng: sudo bash $0 codechalk.tgz [codechalk_db.sql] [codechalk_uploads.tgz]"; exit 1; }
command -v apt-get >/dev/null || { echo "Script này dành cho Ubuntu/Debian."; exit 1; }

set_env() {   # set_env KEY VALUE  — ghi hoặc thay một dòng trong .env
  local k="$1" v="$2"
  if grep -qE "^#?\s*${k}=" .env; then sed -i -E "s|^#?\s*${k}=.*|${k}=${v}|" .env; else printf '%s=%s\n' "$k" "$v" >> .env; fi
}
get_env() {   # đọc giá trị một khoá trong .env (không có thì trả về rỗng, không làm dừng script)
  awk -F= -v k="$1" '$1==k {sub(/^[^=]*=/, ""); v=$0} END {gsub(/^"|"$/, "", v); print v}' .env 2>/dev/null || true
}

# -----------------------------------------------------------------------------
say "1/8 Cập nhật hệ thống và cài công cụ cần thiết"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get -o Dpkg::Options::=--force-confold upgrade -y
apt-get install -y ca-certificates curl tar gzip ufw fail2ban unattended-upgrades python3 dnsutils
systemctl enable --now fail2ban >/dev/null 2>&1 || true
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true
ok "Đã bật tự cập nhật bản vá bảo mật và chặn dò mật khẩu SSH (fail2ban)."

# -----------------------------------------------------------------------------
say "2/8 Tường lửa: chỉ mở SSH (22), HTTP (80), HTTPS (443)"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw --force enable >/dev/null
# Ảnh Ubuntu của Oracle Cloud có sẵn luật iptables chặn mọi cổng trừ 22
if [ -f /etc/iptables/rules.v4 ] && grep -q "REJECT" /etc/iptables/rules.v4; then
  for p in 80 443; do iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || iptables -I INPUT 6 -p tcp --dport $p -j ACCEPT; done
  iptables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT 6 -p udp --dport 443 -j ACCEPT
  command -v netfilter-persistent >/dev/null && netfilter-persistent save >/dev/null 2>&1 || true
  ok "Đã mở cổng 80/443 trong iptables (Oracle Cloud)."
fi
ok "Tường lửa đã bật."

# -----------------------------------------------------------------------------
say "3/8 Bộ nhớ ảo (swap) cho máy ít RAM"
MEM=$(free -m | awk '/^Mem:/{print $2}')
if [ "$MEM" -lt 3500 ] && ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  ok "Đã tạo 2 GB swap (RAM máy: ${MEM} MB)."
else
  ok "Không cần thêm swap (RAM máy: ${MEM} MB)."
fi

# -----------------------------------------------------------------------------
say "4/8 Cài Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null
docker compose version >/dev/null || { warn "Thiếu docker compose plugin."; exit 1; }
ok "$(docker --version)"

# -----------------------------------------------------------------------------
say "5/8 Chép mã nguồn vào ${APP_DIR}"
mkdir -p "$APP_DIR"
tar -xzf "$ARCHIVE" -C "$APP_DIR" --strip-components=1
find "$APP_DIR" -name '*.sh' -exec sed -i 's/\r$//' {} + -exec chmod +x {} +
cd "$APP_DIR"
ok "Xong."

# -----------------------------------------------------------------------------
say "6/8 Cấu hình .env và tên miền"
if [ ! -f .env ]; then
  echo "    Tạo tài khoản HOST và tài khoản nhận tiền VietQR (Enter để giữ giá trị gợi ý)."
  python3 scripts/setup_env.py
fi
[ -f .env ] || { warn "Chưa tạo được .env"; exit 1; }
chmod 600 .env

DOMAIN="$(get_env DOMAIN)"
while :; do
  IN=""
  read -r -p "    Tên miền của web (ví dụ codechalk.io.vn) [${DOMAIN}]: " IN || [ -n "$DOMAIN" ] || { warn "Không đọc được tên miền."; exit 1; }
  DOMAIN="${IN:-$DOMAIN}"
  DOMAIN="$(echo "$DOMAIN" | tr 'A-Z' 'a-z' | sed -e 's#^https\?://##' -e 's#/.*$##' -e 's/^www\.//')"
  [[ "$DOMAIN" =~ ^[a-z0-9.-]+\.[a-z]{2,}$ ]] && break
  warn "Tên miền chưa hợp lệ."
done
set_env DOMAIN "$DOMAIN"
set_env PUBLIC_URL "https://${DOMAIN}"
set_env CORS_ORIGINS "https://${DOMAIN}"
set_env APP_BIND "127.0.0.1"
set_env APP_ENV "production"

MYIP="$(curl -4 -fsS --max-time 8 https://api.ipify.org || curl -4 -fsS --max-time 8 https://ifconfig.me || true)"
while :; do
  DNSIP="$(dig +short A "$DOMAIN" @1.1.1.1 | grep -E '^[0-9.]+$' | tail -1 || true)"
  if [ -n "$MYIP" ] && [ "$DNSIP" = "$MYIP" ]; then ok "Tên miền ${DOMAIN} đã trỏ đúng về máy này (${MYIP})."; break; fi
  warn "Tên miền ${DOMAIN} đang trỏ tới '${DNSIP:-chưa có}', máy này là '${MYIP:-không rõ}'."
  echo "    Vào trang quản lý tên miền, tạo 2 bản ghi:"
  echo "        A      @     ${MYIP:-<IP máy chủ>}"
  echo "        CNAME  www   ${DOMAIN}"
  ANS=""
  read -r -p "    Tạo xong bấm Enter để kiểm tra lại (gõ skip để bỏ qua): " ANS || ANS=skip
  [ "$ANS" = "skip" ] && { warn "Bỏ qua kiểm tra DNS: HTTPS chỉ chạy khi tên miền trỏ đúng IP."; break; }
done

# -----------------------------------------------------------------------------
say "7/8 Dựng và khởi động (lần đầu mất 5–15 phút)"
docker compose --profile vps up -d --build
echo "    Đợi máy chủ sẵn sàng ..."
for i in $(seq 1 90); do
  curl -fsS --max-time 4 http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS --max-time 4 http://127.0.0.1:8000/api/health >/dev/null || { warn "Máy chủ chưa lên. Xem: docker compose logs app"; exit 1; }
ok "Máy chủ đã chạy."

if [ -n "$DB_DUMP" ] && [ -f "$DB_DUMP" ]; then
  echo "    Nạp dữ liệu cũ (tài khoản, bài nộp, cấu hình AI) ..."
  bash deploy/restore.sh "$DB_DUMP" "$UPLOADS"
fi

# -----------------------------------------------------------------------------
say "8/8 Sao lưu tự động lúc 3:30 sáng mỗi ngày (giữ 14 ngày)"
cat > /etc/cron.d/codechalk-backup <<CRON
30 3 * * * root ${APP_DIR}/deploy/backup.sh >> /var/log/codechalk-backup.log 2>&1
CRON
chmod 644 /etc/cron.d/codechalk-backup
ok "Bản sao lưu nằm ở ${APP_DIR}/backups"

echo
echo "    Đang kiểm tra HTTPS ..."
for i in $(seq 1 30); do
  curl -fsS --max-time 6 "https://${DOMAIN}/api/health" >/dev/null 2>&1 && { HTTPS_OK=1; break; }
  sleep 4
done
echo
echo "=============================================================="
if [ "${HTTPS_OK:-0}" = 1 ]; then
  echo "  XONG! CodeChalk đang chạy tại:   https://${DOMAIN}"
else
  echo "  Máy chủ đã chạy. HTTPS cho https://${DOMAIN} sẽ có sau khi tên miền trỏ đúng IP"
  echo "  (Caddy tự thử lại). Xem tiến trình: docker compose logs -f caddy"
fi
echo "  Đăng nhập HOST bằng email/mật khẩu trong .env (hoặc tài khoản cũ nếu đã nạp dữ liệu)."
echo "  Lệnh hữu ích (chạy trong ${APP_DIR}):"
echo "    docker compose logs -f app        # nhật ký máy chủ"
echo "    bash deploy/backup.sh             # sao lưu ngay"
echo "=============================================================="
