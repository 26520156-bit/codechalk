@echo off
REM ==========================================================
REM  Chuyen du lieu ban chay thu (run_dev.bat, SQLite) sang ban Docker (PostgreSQL):
REM  tai khoan, goi, phong thi, bai nop, Bcoins, forum, cau hinh AI, tep tai len.
REM  Du lieu dang co trong PostgreSQL se bi thay the.
REM ==========================================================
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "data\codechalk.db" (
  echo Khong thay data\codechalk.db - chua tung chay run_dev.bat nen khong co gi de chuyen.
  pause
  goto :eof
)
choice /m "Thay toan bo du lieu PostgreSQL bang du lieu tu data\codechalk.db"
if errorlevel 2 goto :eof
docker compose stop app
docker compose run --rm -v "%~dp0data:/import:ro" app python scripts/sqlite_to_postgres.py /import/codechalk.db /import/uploads
if errorlevel 1 (
  echo Chuyen du lieu that bai. Xem loi o tren.
  pause
  goto :eof
)
docker compose start app
echo Xong. Mo http://localhost:8000 va dang nhap nhu cu.
pause
