@echo off
chcp 65001 > nul
cd /d "%~dp0"

rem Python 위치 자동 탐색 (사용자 설치 → 전체 설치 → py 런처)
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%ProgramFiles%\Python312\python.exe" set "PY=%ProgramFiles%\Python312\python.exe"
if not defined PY (
    where py >nul 2>nul && set "PY=py"
)
if not defined PY (
    echo Python 을 찾을 수 없습니다. README 의 설치 2단계를 먼저 진행하세요.
    pause
    exit /b 1
)

"%PY%" -c "import cv2, numpy" 2>nul || "%PY%" -m pip install -r requirements.txt
"%PY%" guide_auto.py %*
pause
