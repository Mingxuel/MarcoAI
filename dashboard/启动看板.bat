@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
set PORT=8765

REM If the server is already listening, just open the browser.
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if %errorlevel%==0 (
    echo MarcoAI UI is already running on port %PORT%. Opening browser...
    start "" "http://127.0.0.1:%PORT%/"
    goto :eof
)

REM Find python: prefer 'py', fallback to 'python'.
where py >nul 2>nul && (
    set "PY=py -3"
) || (
    set "PY=python"
)

echo Starting MarcoAI UI on port %PORT% ...
start "MarcoAI-UI" /min cmd /c "%PY% tools\dashboard_server.py --port %PORT%"

REM Wait up to 30s for the port to come up.
set /a N=0
:wait
timeout /t 1 >nul
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if %errorlevel%==0 goto :ready
set /a N+=1
if %N% LSS 30 goto :wait
echo [WARN] Server did not start within 30s. Check logs\dashboard_server.log
pause
goto :eof

:ready
echo UI ready: http://127.0.0.1:%PORT%/
start "" "http://127.0.0.1:%PORT%/"
