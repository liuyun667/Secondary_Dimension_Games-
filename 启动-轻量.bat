@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 二游毕业指导（轻量）
echo ==============================================
echo   二游毕业指导 · 轻量模式（系统 Python）
echo   无文字识别 / 评分，请用「粘贴文本」「自动导入」
echo   LLM 润色：读取 .env 中的 DEEPSEEK_API_KEY（可选）
echo   浏览器打开 http://127.0.0.1:8000/ ，停止按 Ctrl+C
echo ==============================================

REM 可选：重置数据库（seed 数据升级后建议重建；会清空已保存账户数据）
if exist "data\gyz.db" (
  echo.
  choice /c YN /m "检测到旧数据库，是否删除重建（推荐 Y）？"
  if errorlevel 2 goto :start
  del /q "data\gyz.db" >nul 2>&1
  echo 已删除旧数据库，启动时将自动重建...
  echo.
)

:start
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000/"
python -m uvicorn app.main:app --port 8000
pause
