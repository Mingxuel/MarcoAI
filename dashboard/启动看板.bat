@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo 正在启动 MarcoAI 新看板（端口 8765）...
start "" python tools\dashboard_server.py --port 8765
timeout /t 3 >nul
start "" http://127.0.0.1:8765/
echo 已在浏览器打开 http://127.0.0.1:8765/
