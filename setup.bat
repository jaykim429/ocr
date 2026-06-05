@echo off
chcp 65001 >nul
cd /d "%~dp0"
title QA 시스템 최초 설치

echo ============================================
echo   AI 사전 QA 자동화 시스템 - 최초 설치
echo   (Python 3.10+, Node.js 18+ 가 미리 설치되어 있어야 합니다)
echo ============================================
echo.

where python >nul 2>nul || (echo [오류] python 이 없습니다. https://www.python.org 에서 설치하세요. & pause & exit /b 1)
where npm >nul 2>nul || (echo [오류] Node.js/npm 이 없습니다. https://nodejs.org 에서 설치하세요. & pause & exit /b 1)

echo [1/4] 파이썬 가상환경 생성(.venv)...
if not exist ".venv\Scripts\python.exe" python -m venv .venv

echo [2/4] 백엔드 의존성 설치... (easyocr/torch 포함, 수 GB·수 분 소요)
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
call ".venv\Scripts\python.exe" -m pip install -e .[qa]

echo [3/4] 프런트 의존성 설치...
pushd frontend
call npm install
popd

echo [4/4] (선택) HWP/HWPX 파싱용 kordoc 설치...
call npm install -g kordoc || echo   kordoc 설치 실패는 무시 가능(HWP 파싱만 제한됨)

echo.
echo 설치 완료! run.bat 을 더블클릭하면 실행됩니다.
pause
