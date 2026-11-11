@echo off
chcp 65001 > nul
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=py -3"
%PY% -c "import cv2, numpy" 2>nul || %PY% -m pip install -r requirements.txt
%PY% guide_auto.py %*
pause
