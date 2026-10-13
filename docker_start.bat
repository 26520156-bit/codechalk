@echo off
REM ==========================================================
REM  CodeChalk - chay day du bang Docker (PostgreSQL + may cham)
REM  Nhap dup file nay. Lan dau mat vai phut de dung anh Docker.
REM ==========================================================
setlocal EnableExtensions
cd /d "%~dp0"
set "PORT=8000"

where docker >nul 2>nul
if errorlevel 1 goto :nodocker
docker info >nul 2>nul
if errorlevel 1 goto :noengine

if not exist ".env" (
  echo Chua co file .env - thiet lap lan dau.
  python scripts\setup_env.py
  if not exist ".env" goto :noenv
)

netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
  docker compose ps --status running app 2>nul | findstr /c:"codechalk-app" >nul
  if errorlevel 1 (
    echo [Canh bao] Cong %PORT% dang bi chuong trinh khac dung - thuong la run_dev.bat.
    echo Dong cua so run_dev.bat roi bam phim bat ky de tiep tuc.
    pause
  )
)

echo [1/2] Dung va khoi dong cac container - lan dau mat 3-10 phut ...
docker compose up -d --build
if errorlevel 1 goto :fail

echo [2/2] Doi may chu san sang ...
for /l %%i in (1,1,90) do (
  curl -s -f -o nul http://localhost:%PORT%/api/health && goto :ready
  timeout /t 2 /nobreak >nul
)
goto :slow

:ready
echo.
echo ==========================================================
echo  CodeChalk dang chay.
echo  May nay:            http://localhost:%PORT%
echo  Ban be cung Wi-Fi:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do for /f "tokens=1" %%b in ("%%a") do echo                      http://%%b:%PORT%
echo  Ban be o xa: chay docker_public.bat de lay link cong khai.
echo ==========================================================
start "" "http://localhost:%PORT%"
pause
goto :eof

:slow
echo May chu khoi dong lau hon du kien. Xem nhat ky bang lenh:  docker compose logs -f app
pause
goto :eof

:nodocker
echo Chua cai Docker Desktop. Tai tai https://www.docker.com/products/docker-desktop/ - cai xong khoi dong lai may.
pause
goto :eof

:noengine
echo Docker Desktop chua chay. Mo Docker Desktop, doi chu "Engine running" o goc duoi ben trai, roi chay lai file nay.
pause
goto :eof

:noenv
echo Chua tao duoc file .env. Chay: python scripts\setup_env.py  - hoac chep .env.example thanh .env roi sua.
pause
goto :eof

:fail
echo Khoi dong that bai. Xem dong loi o tren, hoac chay:  docker compose logs app
pause
goto :eof
