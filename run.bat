@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  CTI 로컬 서버 시작
echo ============================================
if not exist ".venv\Scripts\python.exe" (
  echo [1/2] 가상환경을 만듭니다. 처음 한 번만 걸립니다...
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -q --upgrade pip
  .venv\Scripts\python.exe -m pip install -q -r server\requirements.txt
)
if not exist ".env" (
  echo.
  echo  [주의] .env 파일이 없습니다. 특허 검색은 'BQ 미설정'으로 표시됩니다.
  echo         server\.env.example 을 .env 로 복사해 키를 채우십시오.
  echo.
)
echo [2/2] 서버를 켭니다.
echo.
echo   브라우저에서 아래 주소를 여십시오
echo       http://127.0.0.1:8000
echo.
echo   끄려면 이 창에서 Ctrl+C
echo ============================================
start "" http://127.0.0.1:8000
.venv\Scripts\python.exe -m server.main
pause
