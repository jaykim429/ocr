@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI 사전 QA 자동화 시스템 (식품)

echo ============================================
echo   AI 기반 사전 QA 자동화 시스템 - 실행
echo ============================================

REM --- 로그인 계정 (원하면 변경) ---
set QR_ADMIN_USER=admin
set QR_ADMIN_PASS=test1234
set QR_JWT_SECRET=dev-secret

REM --- 파이썬 선택: .venv 있으면 그걸, 없으면 시스템 python ---
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

REM --- 백엔드(FastAPI :8800) 새 창에서 ---
start "QA-Backend :8800" cmd /k "%PY% -m uvicorn chandra_api.app:app --host 127.0.0.1 --port 8800"

REM --- 프런트(Vite :5173) 새 창에서 ---
start "QA-Frontend :5173" cmd /k "cd frontend && npm run dev"

REM --- 서버 기동 대기 후 브라우저 열기 ---
echo 서버 기동 중... (약 6초)
timeout /t 6 /nobreak >nul
start "" http://localhost:5173

echo.
echo  프런트 : http://localhost:5173
echo  백엔드 : http://127.0.0.1:8800
echo  로그인 : %QR_ADMIN_USER% / %QR_ADMIN_PASS%
echo.
echo  ※ 품질검토 판정은 원격 Gemma 서버(222.110.207.7:8000)에 연결되어야 합니다.
echo  창을 닫으면 서버가 종료됩니다.
pause
