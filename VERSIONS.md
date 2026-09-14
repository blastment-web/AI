# 버전 관리

원복이 필요하면 `versions/` 의 파일을 그대로 쓰면 됩니다. 각 버전은 데이터가
내장된 완결형 HTML 이라 다른 파일 없이 단독으로 열립니다.

## V6 에서 바뀐 것 — 판정 로직

경쟁사 수율·원가를 확보할 수 없는 조건에서, 특허·설비투자 공시·대외 기술발표
3축만으로 격차를 추정하도록 판정 로직을 다시 짰습니다. 자세한 내용은
[docs/GAP-MODEL.md](docs/GAP-MODEL.md) 에 있습니다.

| | V5 까지 | V6 |
|---|---|---|
| 특허 관측 구간 | 2025~2026 (2년) | **2010~2026 (16년)** — BigQuery 재추출 |
| 특허 집계 | 수집 건수 그대로 | **패밀리 병합** — 165,650건 → 52,482건 |
| 피인용 수 | 없음 | **53,245건** 확보, 품질 가중에 반영 |
| 방어용 출원 | 공개특허 3건이면 '보유' | 다국 출원·등록 이력 요건 추가 |
| 발표·공시 | 액면가 반영 (공시 1건 → TRL 7) | 특허 뒷받침 없으면 **TRL 6 상한**, 4년 경과 시 등급 하향 |
| 공시 본문 | 제목만 | **본문 217건 확보** — 투자 규모·준공 시점 추출 |
| 격차 | 단일 값 '약 2.25년' | **기준 ~ 보수 밴드** + 신뢰도 등급 |
| 보정 계수 | 없음 | 마케팅 0.75 · 일정 지연 1.35 · 불확실성 여유 15~40% |

바뀐 결과: 근거 **166,274건**(4.2만 → 16.6만), 축 2(양산 진입 격차)
가동 **25/57개 기술**, 신뢰도 '상' 판정 **10건**, 양산 확인(TRL 9) **0건**.

설비투자 공시는 공장 단위 정보라 개별 공정기술에 배정되지 않습니다. 억지로 붙이면
근거 날조가 되므로 **'전사 단위 근거'로 명시 분리**해 신뢰도 상한 0.5로 반영합니다.

분류체계는 **57 → 73개**로 넓혔습니다(활성화 5→10 · Pack 8→14 · 조립 13→18).
신규 편입 16건의 자사 보유 현황은 지어내지 않고 **'확인 필요'** 로 따로 뒀습니다 —
미보유로 처리하면 없는 격차 16건이 생깁니다. 생산기술혁신센터 확인 후 재판정합니다.

**'확인 필요'와 '근거 부족'은 비어 있는 쪽이 정반대입니다.** 확인 필요는 경쟁사
근거는 있는데 자사 현황을 모르는 것(사내 확인으로 풀림), 근거 부족은 자사 현황은
아는데 경쟁사 근거가 없는 것(조사 확대로 풀림)입니다. 둘 다 무채색이라 음영만으로는
구별이 안 되므로 **형태**로 갈랐습니다 — 확인 필요는 채운 배지, 근거 부족은 점선
테두리에 속 빈 배지입니다. 상단 KPI 도 다섯 구분을 전부 세어 합이 전체와 맞습니다.

시급도에는 **대응 기준선**을 붙였습니다. 27점(3×3×3) 검토 착수 · 64점(4×4×4)
계획 반영 · 100점 이상 즉시 착수 — 인자 점수에서 직접 나온 값이며 임의 눈금이 아닙니다.

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
| **V7** | `versions/V7-index.html`<br>`versions/V7-report.pptx` | 2026-09-14 | **판정 논리를 순차 구조로 노출** — '자사 라인 적용 → 경쟁사 확보 → 그래서 구분' 2단계 + 결론. 특허 수가 판정과 어긋나면 경고로 명시. 포트폴리오 카드 클릭 시 모달. '근거 신뢰도'→'근거 등급' 통일, 근거 출처 상시 노출, 미설명 용어·장식 문구 제거 |
| V6 | `versions/V6-index.html`<br>`versions/V6-report.pptx` | 2026-09-13 | **3축 격차 추정 모델**(특허·공시·기술발표) 도입. BigQuery 재추출로 관측 16년치·피인용 확보(165,650건→패밀리 52,482건), 공시 본문 217건 확보로 축 2 가동. 마케팅 보정 0.75·일정 지연 1.35, 기준/보수 듀얼 트랙, 신뢰도 등급. 글자 크기 전면 상향·여백 절반 축소. 포트폴리오 범위 설명 추가 |
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

현재 **346개 모두 통과**합니다(V6 격차 모델 검증 55개 · 판정 기준 125개 포함).
