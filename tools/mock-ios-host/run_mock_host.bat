@echo off
cd /d "%~dp0"
python mock_ios_host.py --host 127.0.0.1 --port 29480
pause
