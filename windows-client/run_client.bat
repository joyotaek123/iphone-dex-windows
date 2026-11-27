@echo off
cd /d "%~dp0"
python src\main.py --mode tcp --host 127.0.0.1 --port 29480 --codec jpeg --fps 30
pause
