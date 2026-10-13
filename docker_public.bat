@echo off
REM ==========================================================
REM  CodeChalk - tao link cong khai cho ban be o xa (Cloudflare Tunnel, mien phi)
REM  Chay docker_start.bat truoc. Link doi moi lan khoi dong lai duong ham.
REM ==========================================================
setlocal EnableExtensions
cd /d "%~dp0"

docker info >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop chua chay. Mo Docker Desktop roi chay lai file nay.
  pause
  goto :eof
)

echo Dang mo duong ham cong khai ...
docker compose --profile public up -d tunnel
if errorlevel 1 (
  echo Khong mo duoc duong ham. Hay chay docker_start.bat truoc.
  pause
  goto :eof
)

set "URL="
for /l %%i in (1,1,30) do (
  for /f "usebackq delims=" %%u in (`powershell -NoProfile -Command "$m = docker compose logs tunnel 2>&1 | Select-String -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -Last 1; if ($m) { $m.Matches[0].Value }"`) do set "URL=%%u"
  if defined URL goto :got
  timeout /t 2 /nobreak >nul
)
echo Chua lay duoc link. Xem nhat ky:  docker compose logs tunnel
pause
goto :eof

:got
echo %URL%| clip
echo.
echo ==========================================================
echo  Link cho ban be (da chep vao clipboard):
echo.
echo     %URL%
echo.
echo  - Giu may tinh bat va Docker Desktop dang chay thi ban be moi vao duoc.
echo  - Link doi moi khi chay lai file nay hoac khoi dong lai may.
echo  - Tat link cong khai:  docker compose stop tunnel
echo ==========================================================
pause
