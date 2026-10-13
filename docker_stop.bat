@echo off
REM  Dung CodeChalk (Docker). Du lieu van duoc giu nguyen trong volume.
cd /d "%~dp0"
docker compose --profile public --profile domain stop
echo Da dung. Chay lai bang docker_start.bat.
pause
