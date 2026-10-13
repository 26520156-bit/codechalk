@echo off
REM ==========================================================
REM  Dua CodeChalk len may chu VPS (Ubuntu 22.04/24.04).
REM  Web chay 24/7 tai https://ten-mien-cua-ban, khong can bat may nay.
REM  Can: IP may chu + mat khau root (nha cung cap VPS gui qua email),
REM       ten mien da tao ban ghi A tro ve IP may chu.
REM ==========================================================
setlocal EnableExtensions
cd /d "%~dp0"
for %%I in (.) do set "DIRNAME=%%~nxI"

set "TAR=%SystemRoot%\System32\tar.exe"
set "SSH=%SystemRoot%\System32\OpenSSH\ssh.exe"
set "SCP=%SystemRoot%\System32\OpenSSH\scp.exe"
if not exist "%TAR%" set "TAR=tar"
if not exist "%SSH%" set "SSH=ssh"
if not exist "%SCP%" set "SCP=scp"
"%SSH%" -V >nul 2>nul
if errorlevel 1 goto :nossh

set "SERVER="
set "SUSER=root"
if exist "deploy\server.txt" for /f "usebackq tokens=1,2" %%a in ("deploy\server.txt") do set "SERVER=%%a" & set "SUSER=%%b"
if /i "%SUSER%"=="enter" set "SUSER=root"
set "IN="
set /p "IN=Dia chi IP may chu VPS [%SERVER%]: "
if defined IN set "SERVER=%IN%"
if not defined SERVER goto :noserver
set "IN="
set /p "IN=Ten dang nhap SSH - bam Enter de dung %SUSER%: "
if defined IN set "SUSER=%IN%"
if /i "%SUSER%"=="enter" set "SUSER=root"
if "%SUSER%"=="" set "SUSER=root"
> "deploy\server.txt" echo %SERVER% %SUSER%

echo.
echo [1/4] Dong goi ma nguon ...
set "PKG=%TEMP%\codechalk.tgz"
"%TAR%" -czf "%PKG%" --exclude=%DIRNAME%/.venv --exclude=%DIRNAME%/.venv-linux --exclude=%DIRNAME%/.env --exclude=*.db --exclude=%DIRNAME%/data/uploads --exclude=%DIRNAME%/data/test_uploads --exclude=%DIRNAME%/.pytest_cache --exclude=__pycache__ --exclude=%DIRNAME%/backups --exclude=%DIRNAME%/deploy/server.txt -C .. "%DIRNAME%"
if errorlevel 1 goto :fail

set "EXTRA="
set "ARGS="
docker info >nul 2>nul
if errorlevel 1 goto :nodata
docker compose ps --status running db 2>nul | findstr /c:"codechalk-db" >nul
if errorlevel 1 goto :nodata
echo.
choice /m "[2/4] Chuyen ca du lieu dang chay tren may nay (tai khoan, bai nop, cau hinh AI) len VPS"
if errorlevel 2 goto :nodata
docker compose exec -T db pg_dump -U codechalk --clean --if-exists --no-owner codechalk > "%TEMP%\codechalk_db.sql"
if errorlevel 1 goto :nodata
docker compose run --rm --no-deps -T --entrypoint tar app -czf - -C /data/uploads . > "%TEMP%\codechalk_uploads.tgz"
set EXTRA="%TEMP%\codechalk_db.sql" "%TEMP%\codechalk_uploads.tgz"
set "ARGS=~/codechalk_db.sql ~/codechalk_uploads.tgz"
echo     Da xuat du lieu.
:nodata

echo.
echo [3/4] Tai len %SUSER%@%SERVER% - lan dau ket noi go "yes", roi nhap mat khau SSH ...
"%SCP%" "%PKG%" "deploy\setup_vps.sh" %EXTRA% %SUSER%@%SERVER%:
if errorlevel 1 goto :fail

echo.
echo [4/4] Cai dat tren may chu - nhap mat khau SSH mot lan nua, roi tra loi cac cau hoi ...
set "SUDO="
if /i not "%SUSER%"=="root" set "SUDO=sudo "
"%SSH%" -t %SUSER%@%SERVER% "sed -i 's/\r$//' ~/setup_vps.sh && %SUDO%bash ~/setup_vps.sh ~/codechalk.tgz %ARGS%"
if errorlevel 1 goto :fail
echo.
echo Xong. Lan sau sua code xong, chay deploy_update.bat de cap nhat len may chu.
pause
goto :eof

:nossh
echo Khong tim thay lenh ssh. Vao Settings - System - Optional features - them "OpenSSH Client", roi chay lai.
pause
goto :eof

:noserver
echo Chua nhap dia chi IP may chu.
pause
goto :eof

:fail
echo.
echo Co loi o buoc tren. Chup man hinh gui lai de duoc ho tro.
pause
goto :eof
