@echo off
cd /d "%~dp0"
echo TOURSTORY Review Crawler v2.0 - Install / repair Python packages
echo.
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -m pip install -r requirements.txt
) else (
  python -m pip install -r requirements.txt
)
echo.
echo Done. Run START.cmd
pause
