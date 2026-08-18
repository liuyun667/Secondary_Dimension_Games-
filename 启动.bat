@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 二游毕业指导（全功能）
echo ==============================================
echo   二游毕业指导 · 全功能模式
echo   RapidOCR 文字识别 / fasttext 分类 / 随机森林评分
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
set GYZ_USE_FASTTEXT=1
set GYZ_USE_RF=1
start "" /min cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8000/"
"D:\ANA\envs\toumanfen\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
