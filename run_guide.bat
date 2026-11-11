@echo off
rem NOTE: keep this file ASCII only. cmd.exe misreads UTF-8 (Korean) text in .bat files.
rem Auto-update and auto-restart are handled by run.py (Python), not by this file,
rem because cmd.exe reads .bat files from disk while running and an update could change this file.
chcp 65001 > nul
cd /d "%~dp0"

set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%ProgramFiles%\Python312\python.exe" set "PY=%ProgramFiles%\Python312\python.exe"
if not defined PY (
    where py >nul 2>nul && set "PY=py"
)
if not defined PY (
    echo [ERROR] Python not found. Please run the install command in README first.
    pause
    exit /b 1
)

"%PY%" -c "import cv2, numpy" 2>nul || "%PY%" -m pip install -r requirements.txt

rem The whole block below is parsed before it runs, so it is safe even if an update rewrites this file.
("%PY%" run.py %* & pause & exit /b)
