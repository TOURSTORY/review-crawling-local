@echo off
cd /d "%~dp0"
where pyw.exe >nul 2>&1
if %errorlevel%==0 (
  start "" pyw.exe -3 main.py
  exit /b
)
where pythonw.exe >nul 2>&1
if %errorlevel%==0 (
  start "" pythonw.exe main.py
  exit /b
)
python main.py
if errorlevel 1 pause
