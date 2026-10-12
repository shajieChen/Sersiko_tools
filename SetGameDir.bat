@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
python "%~dp0tools\set_config.py"
if errorlevel 1 pause
