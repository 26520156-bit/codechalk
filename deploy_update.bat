@echo off
REM ==========================================================
REM  Cap nhat code moi len may chu VPS (giu nguyen du lieu va .env).
REM  Tren may chu tu sao luu truoc khi cap nhat.
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

if not exist "deploy\server.txt" (
  echo Chua co thong tin may chu. Chay deploy_vps.bat truoc.
  pause
  goto :eof
)
for /f "usebackq tokens=1,2" %%a in ("deploy\server.txt") do set "SERVER=%%a" & set "SUSER=%%b"
if /i "%SUSER%"=="enter" set "SUSER=root"
set "SUDO="
if /i not "%SUSER%"=="root" set "SUDO=sudo "

echo [1/3] Dong goi ma nguon ...
set "PKG=%TEMP%\codechalk.tgz"
"%TAR%" -czf "%PKG%" --exclude=%DIRNAME%/.venv --exclude=%DIRNAME%/.venv-linux --exclude=%DIRNAME%/.env --exclude=*.db --exclude=%DIRNAME%/data/uploads --exclude=%DIRNAME%/data/test_uploads --exclude=%DIRNAME%/.pytest_cache --exclude=__pycache__ --exclude=%DIRNAME%/backups --exclude=%DIRNAME%/deploy/server.txt -C .. "%DIRNAME%"
if errorlevel 1 goto :fail

echo [2/3] Tai len %SUSER%@%SERVER% ...
"%SCP%" "%PKG%" %SUSER%@%SERVER%:
if errorlevel 1 goto :fail

echo [3/3] Dung lai va khoi dong tren may chu ...
"%SSH%" -t %SUSER%@%SERVER% "%SUDO%bash /opt/codechalk/deploy/update.sh ~/codechalk.tgz"
if errorlevel 1 goto :fail
echo Xong.
pause
goto :eof

:fail
echo Co loi o buoc tren. Chup man hinh gui lai de duoc ho tro.
pause
