@echo off
cd /d "%~dp0"
echo Installing dependencies...
py -m pip install -r requirements.txt
if errorlevel 1 (
    python -m pip install -r requirements.txt
)
echo.
echo Done. Run the app with: run.bat  or  python main.py
pause
