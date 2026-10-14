@echo off
cd /d "%~dp0"
echo Starting Smart Face Attendance System...
python main.py
if errorlevel 1 (
    echo.
    echo If python failed, try: py -m pip install -r requirements.txt
    echo Then run: py main.py
    pause
)
