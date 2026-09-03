#!/usr/bin/env bash
# CTI 로컬 백엔드 실행. 처음 한 번은 가상환경과 의존성을 만든다.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "▸ 가상환경 생성"
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r server/requirements.txt
fi

if [ ! -f .env ] && [ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]; then
  echo "⚠ .env 도 GOOGLE_APPLICATION_CREDENTIALS 도 없습니다."
  echo "  화면과 서버는 뜨지만 특허 검색은 'BQ 미설정' 상태가 됩니다."
  echo "  cp server/.env.example .env  후 키 경로와 GCP_PROJECT 를 채우십시오."
fi

exec ./.venv/bin/python -m server.main
