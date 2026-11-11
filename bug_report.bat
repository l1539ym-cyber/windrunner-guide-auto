@echo off
rem NOTE: keep this file ASCII only. cmd.exe misreads UTF-8 (Korean) text in .bat files.
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

"%PY%" make_report.py
pause
