@echo off
cd /d %~dp0
python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
if "%ADMIN_PASSWORD%"=="" set ADMIN_PASSWORD=admin123
python application.py
