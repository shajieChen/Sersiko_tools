@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo This reads Data2, Data3 and Data4 from the game directory.
echo Files already present in the resource directory are kept.
echo Close this window if you do not want to extract.
pause
python "%~dp0tools\extract_launch.py"
if errorlevel 1 pause
