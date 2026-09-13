# 버전 관리

원복이 필요하면 `versions/` 의 파일을 그대로 쓰면 됩니다. 각 버전은 데이터가
내장된 완결형 HTML 이라 다른 파일 없이 단독으로 열립니다.

## V6 에서 바뀐 것 — 판정 로직

경쟁사 수율·원가를 확보할 수 없는 조건에서, 특허·설비투자 공시·대외 기술발표
3축만으로 격차를 추정하도록 판정 로직을 다시 짰습니다. 자세한 내용은
[docs/GAP-MODEL.md](docs/GAP-MODEL.md) 에 있습니다.

| | V5 까지 | V6 |
|---|---|---|
| 특허 집계 | 수집 건수 그대로 | **패밀리 병합** — 4만 1,665건 → 2만 2,452건 |
| 방어용 출원 | 공개특허 3건이면 '보유' | 다국 출원·등록 이력 요건 추가 |
| 발표·공시 | 액면가 반영 (공시 1건 → TRL 7) | 특허 뒷받침 없으면 **TRL 6 상한**, 4년 경과 시 등급 하향 |
| 격차 | 단일 값 '약 2.25년' | **기준 ~ 보수 밴드** + 신뢰도 등급 |
| 보정 계수 | 없음 | 마케팅 0.75 · 일정 지연 1.35 · 불확실성 여유 15~40% |

바뀐 결과: 자사 미보유 판정 18건 → **10건**, 양산 확인(TRL 9) → **0건**,
신뢰도 '상' 판정 **0건**(설비투자 공시가 공정기술 단위로 배정되지 않아 2축 교차
검증이 성립하지 않기 때문입니다 — 감추지 않고 그대로 표기합니다).

---

## V4 와 V5 의 차이 — 딱 하나입니다

| | V4 | V5 |
|---|---|---|
| 판독 방식 | **CPC 국제분류 규칙**만 | 규칙 + **LLM 재판독** |
| 비용 | 없음 | LLM 호출 비용 |
| 결과 설명 | 규칙이라 항상 같은 답 | 문맥을 읽지만 매번 같진 않음 |
| 키 | 불필요 | `ANTHROPIC_API_KEY` 필요 |
| 지금 상태 | **바로 씁니다** | 키가 없어 규칙 판독으로 동작 중 |

나머지 화면·데이터·판정 기준은 **완전히 같습니다.** 판독기만 갈아 끼운 구조입니다
(`pipeline/classifier.py` ↔ `pipeline/classifier_llm.py`).

화면 아래쪽 회색 칩에 어느 판독기로 만든 화면인지 늘 찍힙니다. 감추지 않습니다.

### V5 를 실제로 켜려면

`.env` 에 한 줄 넣고 다시 만들면 됩니다.

```
ANTHROPIC_API_KEY=...
```

```bash
.venv\Scripts\python.exe -m pip install anthropic
.venv\Scripts\python.exe pipeline\build_tree.py --engine llm --out data\tree_v5.json
.venv\Scripts\python.exe pipeline\render_html.py --data data\tree_v5.json --out dist\V5-index.html --version v5
```

LLM 은 규칙이 가르지 못한 건에만 묻습니다. 전부 보내지 않습니다 — 돈과 시간을 아끼고,
이미 답이 정해진 건('확정')은 LLM 을 불러도 같은 답이 나오기 때문입니다.

---

## 판 목록

| 버전 | 파일 | 날짜 | 내용 |
|---|---|---|---|
| **V6** | `versions/V6-index.html`<br>`versions/V6-report.pptx` | 2026-09-13 | **3축 격차 추정 모델**(특허·공시·기술발표) 도입. 특허 패밀리 병합(4.2만→2.2만건), 마케팅 보정 0.75·일정 지연 1.35 계수, 기준/보수 듀얼 트랙, 신뢰도 등급. 글자 크기 전면 상향·여백 절반 축소. 포트폴리오 범위 설명 추가 |
| V5 | `versions/V5-index.html`<br>`versions/V5-report.pptx` | 2026-09-13 | V4 와 같고 **LLM 재판독 계층**이 얹혀 있음 (키 없으면 규칙으로 동작) |
| V4 | `versions/V4-index.html`<br>`versions/V4-report.pptx` | 2026-09-13 | 창구 6곳 연결(SEC·논문 신규). 기술 구분을 열위/동등/우위로 재정의. 시급도를 곱셈식으로. 기술 격차에 단계별 이유. 근거 3블록 접기. 수준별 색 분리 |
| V3 | `versions/V3-index.html`<br>`versions/V3-report.pptx` | 2026-09-12 | 실데이터 최초 연결. 근거 팝업·원문 링크. 판정 기준(TRL·격차·시급도) 정립 |
| V2 | git `7706023` | 2026-09-12 | 임원 보고용 공정 파이프라인 뷰 |
| V1 | git `fa44f04` | 2026-09-03 | 대시보드 최초 등록 |

## 되돌리는 법

```bash
:: 화면만 되돌리기 — 파일을 열기만 하면 됩니다
start versions\V3-index.html

:: 코드까지 되돌리기
git checkout v3
git checkout master
```

## 판을 새로 남기는 법

```bash
:: 1) 새 근거만 수집 (이미 받은 건 다시 받지 않습니다)
.venv\Scripts\python.exe pipeline\collect.py
.venv\Scripts\python.exe adapters\capex_sec.py
.venv\Scripts\python.exe adapters\capex_dart.py    --from 20180101
.venv\Scripts\python.exe adapters\capex_cninfo.py  --from 2018-01-01
.venv\Scripts\python.exe adapters\capex_hkex.py    --from 20200101 --deep
.venv\Scripts\python.exe adapters\conf_openalex.py
:: 경쟁사 특허 전량은 분기 1회만 (BigQuery 39GB 스캔)
:: .venv\Scripts\python.exe adapters\patent_bq.py

:: 2) 판정하고 화면 만들기
.venv\Scripts\python.exe pipeline\build_tree.py   --engine rule --out data\tree.json
.venv\Scripts\python.exe pipeline\render_html.py  --data data\tree.json --out dist\V6-index.html --version v6
copy dist\V6-index.html versions\V6-index.html

:: 3) 보고서
.venv\Scripts\python.exe tools\make_ppt.py "docs\경쟁기술_인텔리전스_구조_V6.pptx" V6
```

## 검증

판을 남기기 전에 반드시 돌립니다. 하나라도 실패하면 내보내지 않습니다.

```bash
for %f in (tests\test_*.py) do .venv\Scripts\python.exe %f
```

현재 **338개 모두 통과**합니다(V6 격차 모델 검증 49개 · 판정 기준 123개 포함).
