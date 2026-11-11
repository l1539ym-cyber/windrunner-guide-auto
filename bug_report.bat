@echo off
chcp 65001 > nul
cd /d "%~dp0"

set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%ProgramFiles%\Python312\python.exe" set "PY=%ProgramFiles%\Python312\python.exe"
if not defined PY (
    where py >nul 2>nul && set "PY=py"
)
if not defined PY (
    echo Python 을 찾을 수 없습니다. README 의 설치 방법을 먼저 진행하세요.
    pause
    exit /b 1
)

"%PY%" make_report.py
pause
