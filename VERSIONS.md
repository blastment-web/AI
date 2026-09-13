# 버전 관리

원복이 필요하면 `versions/` 의 파일을 그대로 쓰면 됩니다. 각 버전은 데이터가
내장된 완결형 HTML 이라 다른 파일 없이 단독으로 열립니다.

| 버전 | 파일 | 날짜 | 내용 |
|---|---|---|---|
| **V4** | `versions/V4-index.html`<br>`versions/V4-report.pptx` | 2026-09-13 | CPC 국제분류 기반 판독 적용. 샘플 데이터 제거. 동등·경합·열위 표기. 경쟁사별 조사 건수. 연결 상태 카드 |
| **V3** | `versions/V3-index.html`<br>`versions/V3-report.pptx` | 2026-09-12 | 실데이터 최초 연결. 근거 팝업·원문 링크. 판정 기준(TRL·격차·시급도) 정립 |
| V2 | git 태그 `7706023` | 2026-09-12 | 임원 보고용 공정 파이프라인 뷰 |
| V1 | git 태그 `fa44f04` | 2026-09-03 | 대시보드 최초 등록 |

## 되돌리는 법

```bash
# 화면만 되돌리기 — 파일을 열기만 하면 됩니다
start versions\V3-index.html

# 코드까지 되돌리기
git checkout v3          # V3 시점의 전체 코드
git checkout master      # 다시 최신으로
```

## 버전을 새로 남기는 법

```bash
python -m pipeline.collect          # 새 데이터만 수집
python -m adapters.patent_bq        # 경쟁사 특허 (분기 1회, 39GB)
python -m pipeline.build_tree       # 판정
python -m pipeline.render_html --out dist/V5-index.html
copy dist\V5-index.html versions\V5-index.html
```
