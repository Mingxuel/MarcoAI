@echo off
chcp 65001 >nul
title MarcoAI 策略看板服务
cd /d "%~dp0"

echo ============================================
echo   MarcoAI 策略看板本地服务
echo   启动后请勿关闭本窗口，按 Ctrl+C 停止服务
echo ============================================
echo.

rem 启动服务（后台静默运行）
start /b python -X utf8 ../StrategyService.py --port 8765

rem 等待服务就绪
timeout /t 3 /nobreak >nul

rem 打开浏览器
start http://localhost:8765/

echo 看板已打开： http://localhost:8765/
echo 按任意键退出本窗口（服务将停止）...
pause >nul
