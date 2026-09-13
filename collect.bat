@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PY=.venv\Scripts\python.exe

echo ============================================
echo  근거 수집 -^> 판정 -^> 화면 만들기
echo ============================================
echo.
echo  이미 받은 것은 다시 받지 않습니다. 새로 올라온 것만 받습니다.
echo  전체 약 10~40분 걸립니다. 중간에 끊어도 다음에 이어서 받습니다.
echo.

if not exist "%PY%" (
  echo  [오류] 가상환경이 없습니다. run.bat 을 먼저 한 번 실행하십시오.
  pause & exit /b 1
)

echo [1/8] 국내 특허 ^(KIPRIS^)
%PY% pipeline\collect.py

echo [2/8] 미국 공시 ^(SEC EDGAR^)
%PY% adapters\capex_sec.py

echo [3/8] 국내 공시 ^(DART^)
%PY% adapters\capex_dart.py --from 20180101

echo [4/8] 중국 공시 ^(cninfo^)
%PY% adapters\capex_cninfo.py --from 2018-01-01

echo [5/8] 홍콩 공시 ^(HKEX^) - 본문 PDF 까지 확인하므로 가장 오래 걸립니다
%PY% adapters\capex_hkex.py --from 20200101 --deep

echo [6/8] 학회/논문 ^(OpenAlex^)
%PY% adapters\conf_openalex.py

echo.
echo  [건너뜀] 경쟁사 특허 전량 ^(BigQuery^) - 분기에 한 번만 돌립니다.
echo           한 번에 39GB 를 읽어 무료 한도를 씁니다. 필요할 때만:
echo               %PY% adapters\patent_bq.py
echo.

echo [7/8] 판정 ^(V4 규칙 / V5 LLM^)
%PY% pipeline\build_tree.py --engine rule --out data\tree.json
%PY% pipeline\build_tree.py --engine llm  --out data\tree_v5.json

echo [8/8] 화면 만들기
%PY% pipeline\render_html.py --data data\tree.json    --out dist\V4-index.html --version v4
%PY% pipeline\render_html.py --data data\tree_v5.json --out dist\V5-index.html --version v5

echo.
echo ============================================
echo  끝났습니다.
echo    dist\V4-index.html   ^(규칙 판독 - 바로 씁니다^)
echo    dist\V5-index.html   ^(LLM 판독 - 키가 있을 때만 켜집니다^)
echo  파일을 더블클릭하면 서버 없이 바로 열립니다.
echo ============================================
pause
