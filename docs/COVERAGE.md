# 수집 커버리지 진단

> 대상: 경쟁사 신호 수집 어댑터 구성
> 방법: 화면(`index.html`)이 코드로 선언한 출처 계보 `originOf()` 규칙에 근거 61건을 태워
> 어느 어댑터가 무엇을 책임지는지 실측
> 재현: `python3 tools/coverage_audit.py` — 이 문서의 모든 수치는 이 스크립트 출력이다

---

## 요약

| 지표 | 값 |
|---|---|
| 구현된 어댑터로 수집 가능한 근거 | **18 / 61건 (30%)** |
| 판정을 좌우하는 고등급(VERIFIED·STRONG) 중 수집 불가 | **22 / 28건** |
| 컨퍼런스 신호 커버리지 | **0 / 20건** |
| 특허 중 청구항에 도달하지 못하는 건 | **8 / 21건 (38%)** |

**결론 한 줄 — 국내 특허는 빈틈이 없다. 뚫린 곳은 글로벌 3개 관할(CN·US·JP)과 컨퍼런스 전체이며,
하필 판정을 만드는 고등급 근거가 거기 몰려 있다.**

지금 상태로 파이프라인을 돌리면 화면의 GAP 판정이 재현되지 않는다.
판정 규칙이 `STRONG 1건 = 보유`인데, 그 STRONG의 대부분을 가져올 수 없기 때문이다.

---

## 1. 각 어댑터가 무엇을 끌어오려던 것인가

계보 선언에서 복원한 의도. `capex_*`는 **"돈이 실제로 움직였는가"**, `patent_*`는
**"청구항에 공정 조건이 적혀 있는가"** 를 잡는다. 등급 사다리에서 맡는 자리가 서로 다르다.

| 어댑터 | 끌어오는 정보 | 담당 등급 | 키 |
|---|---|---|---|
| `capex_sec.py` | TESLA의 8-K 법정공시 — 라인 증설·발주 사실 | VERIFIED | 불필요 |
| `capex_dart.py` | 삼성SDI·SK온 신규시설투자 공시 | VERIFIED / STRONG | 필요 |
| `patent_kipris.py` | 국내 출원·등록 청구항 — 공정 조건 | MEDIUM / WEAK | 필요 |
| `patent_epo.py` | EP·WO 문헌 + **INPADOC 가족 ID(중복제거 마스터키)** | MEDIUM / WEAK | 필요 |
| `conf_openalex.py` | 학술 문헌 | — (§5 참조) | 불필요 |

`patent_epo.py`는 특허 수집과 별개로 **모든 어댑터의 중복제거 키를 공급하는 축**이라는 점이
다른 넷과 다르다. §6에서 다시 다룬다.

---

## 2. 어댑터별 귀속 — 근거 61건 실측

| 라우팅 대상 | 건수 | 상태 | 등급 분포 |
|---|---:|---|---|
| 컨퍼런스 프로그램 파싱 | 20 | 미구현 (OpenAlex로 대체됨) | medium 12 · strong 8 |
| cninfo 파싱 | 13 | 미구현 | strong 8 · verified 5 |
| EPO OPS | 9 | 구현 | weak 7 · medium 2 |
| Google Patents (BQ) | 9 | 미구현 | weak 7 · medium 2 |
| SEC EDGAR | 4 | 구현 | verified 4 |
| KIPRIS | 3 | 구현 | weak 3 |
| DART | 2 | 구현 | verified 1 · strong 1 |
| EDINET / TDnet | 1 | **구성표에 항목조차 없음** | verified 1 |

| 신호 유형 | 총건수 | 수집 가능 | 비율 |
|---|---:|---:|---:|
| 특허 | 21 | 12 | 57% |
| 설비투자 | 20 | 6 | 30% |
| 컨퍼런스 | 20 | 0 | **0%** |

### 고등급 근거일수록 못 가져온다

VERIFIED·STRONG 28건 중 **22건이 미구현 어댑터 소관**이다.

| 미구현 소관 | 고등급 건수 |
|---|---:|
| cninfo 파싱 | 13 |
| 컨퍼런스 프로그램 파싱 | 8 |
| EDINET / TDnet | 1 |

여기 걸리는 실물: CATL Fujian 3期·Debrecen 2단계·Yibin 제로카본, BYD Jinan·Changzhou,
PANASONIC Wakayama 4680 — 전부 "양산 가동이 확인된" 최상위 근거다.

---

## 3. 관할별 커버리지 — 국내 / 국제 / 글로벌

| 구분 | 관할 | 계보상 원천 | 상태 | 청구항 |
|---|---|---|---|---|
| 국내 | KR | KIPRIS Plus | 구현 | ○ |
| 국제 | WO / PCT | EPO OPS (DOCDB에 WO 포함) | 구현 | ○ |
| 국제 | EP | EPO OPS | 구현 | ○ |
| 글로벌 | CN | Google Patents (BQ) | **미구현** | ○ (구현 시) |
| 글로벌 | US | EPO OPS로 라우팅됨 | 구현이나 **부적합** | ✘ 서지만 |
| 글로벌 | JP | EPO OPS로 라우팅됨 | 구현이나 **부적합** | ✘ 서지만 |

- **국내는 빈틈 없다.** KIPRIS가 KR을 1차 출처로 직결한다. 외국 기업의 KR 출원도 함께 잡히므로
  경쟁사 교차 확인에도 쓸 수 있다.
- **국제(PCT)는 전용 어댑터가 없지만 빈틈이 아니다.** EPO OPS가 WO 문헌을 포괄한다.
  WIPO PATENTSCOPE는 공식 REST API가 없어 별도로 붙일 실익이 약하다.
- **글로벌은 셋 다 뚫려 있다.** CN은 어댑터 자체가 없고, US·JP는 어댑터는 돌지만 청구항에
  닿지 못한다.

발행관할 분포 (특허 21건): CN 7 · US 5 · WO 3 · JP 3 · KR 3

---

## 4. 구조적 문제 ① — 라우팅 축이 '기업 국적'이다

`originOf()`는 **기업 국적**으로 원천을 고른다(CATL→BQ, TESLA→EPO OPS).
그러나 특허는 **어디에 공개됐는가(발행관할)** 로 원천이 정해져야 한다.

그 결과 US 5건·JP 3건이 모두 EPO OPS로 가는데, OPS는 이들에 대해 서지와 영문초록까지만 준다.
**특허 21건 중 8건(38%)이 청구항에 도달하지 못한다.**

판정 규칙의 `MEDIUM = 등록특허의 구체적 공정 조건`은 청구항을 읽어야 성립한다.
따라서 현재 설계에서 **TESLA·PANASONIC 특허는 구조적으로 WEAK을 넘을 수 없다.**

이미 규칙과 어긋난 항목이 있다:

- `TESLA US 11,987,442 B2 (등록)` — **MEDIUM이 부여돼 있으나 근거인 청구항을 가져올 경로가 없다.**
- `TESLA US 2026/0098231 A1` — 요약이 "Claim 1에 전단률·온도 창을 수치로 한정"이라고
  청구항을 직접 인용한다. WEAK이지만 이 문장 자체가 청구항 없이는 쓸 수 없다.

> **목업 수치를 안심 근거로 삼지 말 것.** 목업에서 국적 ≠ 발행관할은 3/21건(14%)에 그치지만,
> 이는 목업과 라우터를 같은 사람이 썼기 때문이다. 실제로는 CATL이 EP·US·KR에,
> TESLA가 CN·JP·KR에 폭넓게 출원하므로 실수집에서는 이 비율이 크게 올라간다.

**권고** — 라우팅 축을 `기업 국적` → `발행관할 × 신선도`로 바꾼다.

---

## 5. 구조적 문제 ② — OpenAlex는 필요한 증거 종류를 못 가져온다

화면이 인용한 컨퍼런스 출처 10곳 중 OpenAlex가 색인할 만한 학술 행사는 **IEEE VPPC 하나**다.

| 출처 | 성격 | OpenAlex |
|---|---|---|
| IEEE VPPC | 학술 학회 (DOI 있음) | ○ |
| CIBF 2026 | 전시회 | ✘ |
| AABC Europe 2026 | 산업 컨퍼런스 | ✘ |
| The Battery Show Japan | 전시회 | ✘ |
| IBS 2026 | 산업 세미나 | ✘ |
| Battery Japan | 전시회 | ✘ |
| Battery Safety Summit | 산업 컨퍼런스 | ✘ |
| LASER World of PHOTONICS | 전시회 부대 세션 | ✘ |
| Automate 2026 | 전시회 | ✘ |
| Investor Day 부대 세션 | 기업 행사 | ✘ |

전시회·산업 컨퍼런스·기업 행사는 DOI가 없어 OpenAlex에 들어오지 않는다.

더 큰 문제는 **등급 사다리(`GRADE`)에 학술 논문 항목이 없다**는 점이다. OpenAlex 산출물을
`conf`로 넣으면 `기술세션 발표(MEDIUM)`로 오분류된다.

**권고** — 둘 중 하나.
1. OpenAlex를 **새 증거 종류**(예: `paper`, 산학 공동연구 방향성 신호)로 분리하고 등급 정의를 추가
2. 컨퍼런스 커버리지는 전시 프로그램 파싱으로 따로 채우고 OpenAlex는 보류

어느 쪽이든 **OpenAlex는 컨퍼런스 어댑터의 대체재가 아니다.**

---

## 6. 구조적 문제 ③ — 중복제거 마스터키가 EPO에 묶여 있다

`originOf()`는 KR·기타 모두 dedup 키로 `INPADOC Family ID`를 선언한다. INPADOC은 EPO 데이터다.
따라서 KIPRIS나 BigQuery로 수집한 레코드도 **가족 ID를 얻으려면 매 건 EPO OPS를 경유해야 한다.**

EPO OPS 무료 계정에는 처리량 상한이 있으므로, 수집량이 늘수록 여기가 병목이 된다.

**권고** — BigQuery의 `family_id`(DOCDB 단순 가족)를 마스터로 쓰고, EPO는 INPADOC 확장 가족이
필요한 건에 한해 보강으로 돌린다.

---

## 7. BigQuery를 글로벌 백본으로 쓰면 관할 3개가 한 번에 닫힌다

`patents-public-data.patents.publications`는 US·CN·JP·KR·EP·WO를 **한 테이블에서**
청구항(`claims_localized`)까지 제공한다. `server/bq.py`가 이미 이 테이블을 조회하고 있어
클라이언트·쿼리 조립·비용 가드를 그대로 재사용할 수 있다.

- **장점** — GCP 키 하나로 6개 경쟁사 전 관할 청구항 확보. **USPTO·JPO 키 발급이 불필요해진다.**
- **한계** — 갱신 주기가 분기 단위라 "매일 드러냅니다"라는 제품 요건을 혼자서는 못 채운다.

**따라서 역할을 나눠야 한다.**

| 역할 | 담당 | 하는 일 |
|---|---|---|
| 전수·청구항 백본 | Google Patents BQ | 전 관할 청구항 확보, 가족 ID 마스터 |
| 신선도 보강 | KIPRIS · EPO OPS · (필요 시 USPTO) | 신규 공개 주간/일간 추적 |

현재 구성표에는 이 분담이 없다. 관청 API를 '관할 담당'으로 두고 있어 서로 겹치면서도 빈다.

---

## 8. 키 발급 체크리스트

### 발급이 필요한 것 (받는 대로 연결)

| 원천 | 필요한 것 | 발급처 | 비고 |
|---|---|---|---|
| **Google Patents BQ** | GCP 서비스 계정 JSON | GCP 콘솔 | **최우선.** 이것 하나로 CN·US·JP 청구항이 전부 열린다 |
| KIPRIS Plus | 서비스키 | plus.kipris.or.kr | 무료 |
| EPO OPS | Consumer Key / Secret | developer.epo.org | 무료, OAuth2 |
| DART | API 키 | opendart.fss.or.kr | 무료 · **어댑터 구현 완료** (`adapters/capex_dart.py`) |
| EDINET v2 | Subscription-Key | disclosure2.edinet-fsa.go.jp | 2023-08부터 필수 · MFA 필요 |
| USPTO ODP | API 키 | data.uspto.gov | 2026-03 PatentsView 통합 · MFA + 프로필 추가 항목 필수. **BQ로 대체 가능하므로 후순위** |

> USPTO와 EDINET은 과거에 키 없이 쓰던 경로가 막혔다. 둘 다 현재는 계정 + MFA가 필요하다.

### 키 없이 연결 가능한 것

| 원천 | 조건 |
|---|---|
| SEC EDGAR | 키 불필요. 연락처 이메일을 User-Agent에 넣는 것이 요구사항 |
| OpenAlex | 키 불필요 (`mailto=`로 polite pool). 단 §5의 역할 재정의가 선행되어야 함 |
| cninfo 공고 | 공식 API 없음. HTTP 파싱 — ToS·robots 확인이 선행 |
| 컨퍼런스 프로그램 | 행사별 PDF/웹 파싱. 사이트마다 개별 구현 필요 |

---

## 9. 권장 우선순위

고등급 근거 회수량 기준.

| 순위 | 대상 | 회수하는 근거 | 이유 |
|---|---|---|---|
| 1 | **Google Patents BQ** | 특허 9건 + US·JP 8건의 청구항 | 키 1개로 관할 3개 해결. `server/bq.py` 재사용 가능 |
| 2 | **cninfo** | 고등급 13건 (verified 5 · strong 8) | 단일 최대 공백. CATL·BYD 양산 신호 전체 |
| 3 | **컨퍼런스 프로그램 파싱** | 고등급 8건 | 현재 커버리지 0%. OpenAlex로 대체 불가 |
| 4 | EDINET v2 | verified 1건 | 구성표 누락 항목. PANASONIC 담당 |
| 5 | USPTO ODP | (BQ와 중복) | BQ 도입 후 신선도 보강 용도로만 |

병행 과제 — §4 라우팅 축 전환, §5 OpenAlex 역할 재정의, §6 dedup 마스터키 이전.
이 셋은 어댑터를 더 붙이기 전에 정해야 나중에 재작업이 없다.

---

## 부록 — 이 문서의 수치를 다시 뽑는 법

```bash
python3 tools/coverage_audit.py          # 사람이 읽는 보고서
python3 tools/coverage_audit.py --md     # 마크다운 표
```

`index.html`의 `TREE_MOCK`을 파싱하므로, 목업이 실수집 데이터로 바뀌면 같은 명령으로
커버리지를 다시 측정할 수 있다. 어댑터 구현 상태는 스크립트 상단 `STATUS` 딕셔너리에서 고친다.
