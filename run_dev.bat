@echo off
REM ==========================================================
REM  CodeChalk Platform - chay thu tren Windows (SQLite)
REM  Nhap dup file nay. Lan dau se tao .venv va cai thu vien.
REM ==========================================================
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"

REM ---- Chon Python: uu tien 3.13, 3.12, 3.11 (co san du thu vien dung san) ----
set "PY="
for %%V in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY goto :nopython
set "PYVER="
for /f "tokens=2" %%v in ('%PY% -V 2^>^&1') do set "PYVER=%%v"
echo Dung Python %PYVER%  [%PY%]

REM ---- Lan cai truoc bi loi: xoa .venv cu de tao lai ----
if exist ".venv\Scripts\python.exe" if not exist ".venv\.installed" (
  echo Lan cai truoc chua xong, tao lai moi truong .venv ...
  rmdir /s /q ".venv"
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Tao moi truong ao .venv ...
  %PY% -m venv .venv
  if errorlevel 1 goto :nopython
)

if not exist ".venv\.installed" (
  echo [2/3] Cai thu vien Python - chi lan dau, can mang ...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --prefer-binary -r requirements.txt
  if errorlevel 1 goto :fail
  ".venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, pydantic_core, jwt, qrcode, websockets"
  if errorlevel 1 goto :blocked
  echo ok> ".venv\.installed"
)

if not exist ".env" (
  echo.
  echo Thiet lap lan dau: nhap tai khoan HOST va tai khoan nhan tien VietQR.
  ".venv\Scripts\python.exe" scripts\setup_env.py
)
if not exist ".env" goto :noenv

where g++ >nul 2>nul
if errorlevel 1 echo [Luu y] Chua thay g++: bai C++ se bao "chua cai g++". Cai MSYS2 + mingw-w64 hoac dung Docker.

echo [3/3] Khoi dong may chu tai http://localhost:8000   - bam Ctrl+C de dung
start "" /min cmd /c "timeout /t 5 /nobreak >nul & start http://localhost:8000"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if errorlevel 1 (
  echo.
  echo May chu dung vi loi. Chup man hinh dong loi mau do o tren gui lai de duoc ho tro.
  pause
)
goto :eof

:nopython
echo.
echo Khong tim thay Python. Cai Python 3.13 tu https://www.python.org/downloads/ - nho tick "Add python.exe to PATH" - roi chay lai.
pause
goto :eof

:noenv
echo.
echo Chua tao duoc file .env. Chay lai run_dev.bat, hoac chep .env.example thanh .env roi sua tay.
pause
goto :eof

:blocked
echo.
echo Thu vien da cai nhung Windows khong cho nap. Neu dong loi co chu "Application Control policy has blocked",
echo do la Smart App Control cua Windows dang chan. Xem muc "Loi thuong gap" trong README.md.
pause
goto :eof

:fail
echo.
echo Cai thu vien that bai. Xem dong ERROR mau do o tren.
echo  - Neu dang dung Python 3.14 tro len: cai them Python 3.13 tu python.org roi chay lai file nay.
echo  - Neu thay "Application Control policy has blocked": xem muc "Loi thuong gap" trong README.md.
pause
goto :eof
