"""기술 판독 에이전트 — 이 특허가 어느 공정기술의 것인가.

용어 매칭만으로는 안 된다는 것을 실측으로 확인했다(느슨하면 한 기술에 7,674건,
빡빡하면 4만 건 중 228건). 그래서 판단 근거를 셋으로 늘렸다.

  1. CPC / IPC  — 특허청이 직접 부여한 국제 표준 기술분류. 가장 신뢰도가 높다.
  2. 특징 용어   — 그 기술에만 쓰이는 말 (예: 파이브릴화, 슬롯다이, 탭리스)
  3. 배제 용어   — 있으면 그 기술이 아님을 뜻하는 말

세 신호를 합쳐 '확정 / 추정 / 관련' 세 단계로 나눈다. 확정·추정만 판정에 쓰고
관련은 참고로만 둔다. 왜 그렇게 분류했는지는 레코드마다 남긴다.

LLM 을 쓰지 않는다. 규칙이 눈에 보이고, 돈이 들지 않으며, 같은 입력에 항상 같은
답을 준다. 나중에 LLM 을 붙이려면 classify() 만 교체하면 된다.
"""
from __future__ import annotations

import re

# ── CPC/IPC → 기술 노드 ──────────────────────────────────────────────
# 키는 노드 이름. 값은 그 기술을 가리키는 CPC 접두어 목록.
# 배터리 제조공정의 표준 분류를 따랐다.
NODE_CPC = {
    # 전극 · 믹싱
    "고형분 상향 슬러리 (≥72%)":      ["H01M4/62", "H01M4/139", "H01M4/04"],
    "연속식 믹서 (Planetary→CTM)":    ["B01F", "H01M4/04", "H01M4/139"],
    "무용매 PTFE 파이브릴화":          ["H01M4/62", "H01M4/139", "C08J5", "H01M4/04"],
    "CNT 도전재 고분산":              ["H01M4/62", "C01B32", "H01M4/583", "H01M4/587"],
    "슬러리 물성 AI 예측":             ["G06N", "H01M4/04", "G01N11"],
    # 전극 · 코팅
    "양면 동시 코팅":                 ["B05C", "B05D", "H01M4/04"],
    "무용매 건식 코팅·라미네이션":       ["H01M4/04", "H01M4/139", "B05D1", "B32B"],
    "광폭 고속 코팅 (>100 m/min)":    ["B05C", "B05C5", "H01M4/04"],
    "다층(Dual-layer) 슬롯다이":       ["B05C5", "B05C9", "H01M4/36"],
    "저온 건조 (IR·유도가열)":         ["F26B", "H01M4/04", "H05B6"],
    "패턴/스트라이프 코팅":             ["B05D1", "B05C1", "H01M4/04"],
    "인라인 코팅 두께 X-ray 계측":      ["G01B15", "G01N23", "G01B11"],
    # 전극 · 롤프레스
    "고밀도 압연 (≥3.6 g/cc)":        ["B30B", "B21B", "H01M4/04"],
    "열간 롤프레스":                  ["B30B", "B21B1", "H01M4/04"],
    "두께 폐루프 실시간 제어":          ["B21B37", "G05B19", "G01B"],
    "롤 크라운 능동 보정":             ["B21B27", "B21B37"],
    "전극 크랙 인라인 검사 (AI)":       ["G01N21", "G06T7", "G06V", "G01N21/88"],
    # 전극 · 슬리팅
    "레이저 슬리팅":                  ["B23K26", "B26D", "H01M4/04"],
    "버(Burr) 저감 시어 슬리팅":        ["B26D", "B23D", "B26F"],
    "광폭 다열 슬리팅":                ["B26D", "B65H35"],
    "엣지 이물 비전 검사":             ["G01N21", "G06T7", "G06V"],
    # 조립 · DNC
    "고속 레이저 노칭 (>120 ppm)":     ["B23K26", "H01M10/04", "B26F1"],
    "Z-스태킹 고속화":                ["H01M10/0585", "H01M10/04"],
    "라미네이션 & 스태킹 (L&S)":        ["H01M10/0583", "H01M10/0585", "B32B"],
    "스택 정렬 실시간 비전 보정":        ["G06T7", "G06V", "H01M10/04"],
    "초음파 탭 용접 품질 AI 판정":       ["B23K20", "H01M50/50", "B23K31"],
    "전극 탭 표면 클리닝":              ["B23K26/40", "B08B7", "H01M50/536", "C23G"],
    # 조립 · AZS
    "탭리스(Tabless) 젤리롤 와인딩":     ["H01M10/0587", "H01M50/53", "H01M50/531"],
    "46-시리즈 대형 원통 양산":         ["H01M50/10", "H01M10/0587", "H01M50/107"],
    "진공 주액 사이클 최적화":          ["H01M50/60", "H01M50/609", "H01M10/04"],
    "케이스 레이저 용접 실시간 감시 (OCT)": ["B23K26", "G01B9", "H01M50/17"],
    "셀 투 팩 직결 조립 (모듈리스)":     ["H01M50/20", "H01M50/204", "B60K1"],
    "젤리롤 프레싱·삽입":               ["H01M10/0587", "H01M50/107", "B30B", "H01M10/04"],
    "헬륨 리크 테스트 자동화":           ["G01M3/20", "G01M3/04", "H01M50/183", "G01M3/22"],
    "캡 어셈블리 자동 조립":             ["H01M50/152", "H01M50/30", "H01M50/166", "B23P19"],
    # 조립 · PKG
    "파우치 딥드로잉 포밍":             ["B21D22", "H01M50/105", "B21D51"],
    "디게싱 자동화 라인":              ["H01M10/52", "H01M50/30", "H01M50/apt"],
    "셀 외관 AI 검사 (멀티모달)":       ["G01N21", "G01N29", "G06T7", "G06V"],
    "레이저 실링 (파우치)":            ["B23K26", "B29C65", "H01M50/19"],
    "가스포켓 절단·재실링":             ["H01M50/30", "H01M10/52", "B26D", "H01M50/19"],
    # 활성화
    "고전류 급속 활성화":               ["H01M10/44", "H02J7", "H01M10/0525"],
    "가압 활성화 (Pressurized formation)": ["H01M10/44", "H01M10/04", "H01M10/052"],
    "에이징 기간 단축 알고리즘":         ["H01M10/48", "G01R31/392", "G01R31/367"],
    "활성화 데이터 기반 불량 예측 (AI)":   ["G01R31/367", "G01R31/378", "G06N"],
    "고속 자가방전 선별 (μA급)":        ["G01R31/389", "G01R31/3835", "G01R31/396"],
    "SEI 형성 프로파일 정밀 제어":       ["H01M10/44", "H01M10/0525", "H02J7/00", "H01M4/1391"],
    "OCV 편차 기반 불량 선별":          ["G01R31/396", "G01R31/367", "G01R31/3842"],
    "활성화 충방전 에너지 회생":         ["H02J7/00", "H02M3", "H02J7/34", "H02J3/32"],
    "마이크로 단락 조기 검출":           ["G01R31/52", "G01R31/385", "H01M10/48", "G01R31/36"],
    "활성화 챔버 온도 편차 제어":        ["H01M10/613", "H01M10/6563", "F24F11", "H01M10/44"],
    # Pack · 구조
    "CTP (Cell to Pack)":            ["H01M50/20", "H01M50/204", "H01M50/249"],
    "CTC / CTB 차체 일체화":          ["B60K1/04", "H01M50/249", "B62D"],
    "구조용 접착 자동 도포":            ["C09J", "H01M50/24", "B05C"],
    "버스바 레이저 용접":               ["B23K26", "H01M50/503", "H01M50/51", "B23K101"],
    "냉각판 일체형 브레이징":            ["B23K1", "H01M10/6556", "F28F3", "H01M10/6568"],
    "셀 간 방염·단열 패드 자동 적용":     ["H01M10/653", "H01M10/658", "H01M50/291", "B32B"],
    # Pack · 안전
    "열폭주 전파 차단 구조":            ["H01M10/658", "H01M50/207", "A62C", "H01M10/653"],
    "무선 BMS (wBMS)":               ["H01M10/42", "H04W", "G01R31/396", "H02J7/00"],
    "클라우드 BMS 진단·수명 예측":       ["G01R31/367", "G01R31/392", "G06Q", "H02J7/00"],
    "화재 조기감지 센서 내장":           ["G08B17", "H01M50/30", "G01N33", "H01M10/48"],
    "팩 기밀 자동 검사 (IP67)":         ["G01M3", "G01M3/26", "H01M50/183", "G01M3/32"],
    "팩 EOL 통합 검사":                ["G01R31/385", "G01R31/396", "G01R31/50", "H01M10/48"],
    "액침 냉각 구조":                  ["H01M10/6567", "H01M10/6569", "H01M10/613", "F28D15"],
    # 인프라
    "AMR 기반 무인 공정간 반송":        ["B65G", "G05D1", "B65G1"],
    "전극 롤 자동 반송·보관":           ["B65G1", "B65H", "B65G47"],
    "물류 디지털 트윈 시뮬레이션":       ["G06F30", "G05B19/418", "G06Q10"],
    "드라이룸 폐열회수 제습":           ["F24F", "B01D53/26", "F24F12"],
    "공정 폐열 재활용 네트워크":         ["F28D", "F24F12", "F01K"],
    "탄소배출 실시간 모니터링 (제품 LCA)": ["G06Q50", "Y02P", "G06Q10/06"],
    "재생에너지 직접 연계 운영":         ["H02J3", "Y02E", "H02J15"],
    "모듈러 공장 공법":                ["E04B1/348", "E04H5", "E04B"],
    "Copy-Exact 표준 라인 패키지":      ["G05B19/418", "G06Q10"],
    "증설 리드타임 단축 공법":          ["E04H5", "E04G", "G06Q10"],
    # 차세대 케미스트리
    "소듐이온 배터리 양산":             ["H01M10/054", "H01M4/58", "H01M10/0525", "C01D"],
    "이종 케미스트리 복합 팩 (AB 시스템)": ["H01M10/42", "H01M50/20", "H02J7/00", "G01R31/396"],
    "초급속 충전 LFP (4C급)":          ["H01M4/58", "H01M4/136", "H01M10/44", "H01M4/62"],
    "반고체 고에너지 셀 (응축형)":       ["H01M10/056", "H01M10/0562", "H01M10/052", "H01M4/62"],
    # 차세대 사업모델
    "기술 라이선스 공급 (LRS)":         ["G06Q50/18", "G06Q10/06", "G06Q30"],
    "배터리 교환 서비스 (BaaS)":        ["B60S5/06", "H02J7/00", "B60L53/80", "G06Q50/06"],
    # Pack 구조·열관리
    "모듈리스 체적효율 극대화 (CTP 3.0)": ["H01M50/20", "H01M50/204", "H01M50/249", "B60K1/04"],
    "냉각·단열·구조 일체형 열관리":      ["H01M10/6556", "H01M10/653", "H01M10/6568", "H01M50/291"],
    # 스마트 제조
    "전 공정 폐루프 자율 보정":          ["G05B19/418", "G05B13", "G01N21/88", "B21B37"],
    "십억분율 결함 관리 (DPB)":         ["G05B19/418", "G01N21/88", "G06Q10/06", "G06T7"],
    "엣지 AI 기반 초고속 택트":          ["G05B19/418", "G06N3", "B25J9", "G05D1"],
}

# ── 특징 용어 — 그 기술에만 쓰이는 말 ────────────────────────────────
NODE_TERMS = {
    "고형분 상향 슬러리 (≥72%)":      ["고형분", "solid content", "high solid", "슬러리"],
    "연속식 믹서 (Planetary→CTM)":    ["연속식", "트윈스크루", "twin screw", "continuous mix", "혼련"],
    "무용매 PTFE 파이브릴화":          ["ptfe", "파이브릴", "fibril", "무용매", "solvent-free", "건식 바인더"],
    "CNT 도전재 고분산":              ["cnt", "탄소나노튜브", "carbon nanotube", "도전재", "conductive agent"],
    "슬러리 물성 AI 예측":             ["점도", "viscosity", "유변", "rheolog", "예측"],
    "양면 동시 코팅":                 ["양면", "double-side", "both side", "동시 코팅", "dual side"],
    "무용매 건식 코팅·라미네이션":       ["건식 전극", "dry electrode", "무용매", "solvent-free", "라미네이션", "dry coating"],
    "광폭 고속 코팅 (>100 m/min)":    ["광폭", "고속 코팅", "high speed coat", "wide web", "코터"],
    "다층(Dual-layer) 슬롯다이":       ["슬롯다이", "slot die", "다층", "dual layer", "이층"],
    "저온 건조 (IR·유도가열)":         ["근적외선", "infrared", "유도가열", "induction heat", "저온 건조", "건조로"],
    "패턴/스트라이프 코팅":             ["무지부", "패턴 코팅", "stripe", "intermittent", "간헐"],
    "인라인 코팅 두께 X-ray 계측":      ["x-ray", "엑스레이", "로딩량", "두께 측정", "thickness gauge", "basis weight"],
    "고밀도 압연 (≥3.6 g/cc)":        ["압연", "calender", "밀도", "density", "프레스"],
    "열간 롤프레스":                  ["열간", "hot press", "heated roll", "가열 롤"],
    "두께 폐루프 실시간 제어":          ["폐루프", "closed loop", "갭 제어", "gap control", "두께 제어"],
    "롤 크라운 능동 보정":             ["크라운", "crown", "롤 변형", "roll bend"],
    "전극 크랙 인라인 검사 (AI)":       ["크랙", "crack", "결함 검출", "defect detect", "표면 검사"],
    "레이저 슬리팅":                  ["레이저 슬리팅", "laser slit", "laser cut", "레이저 절단"],
    "버(Burr) 저감 시어 슬리팅":        ["버", "burr", "시어", "shear", "나이프", "slitting"],
    "광폭 다열 슬리팅":                ["다열", "multi lane", "multi-lane", "광폭"],
    "엣지 이물 비전 검사":             ["엣지", "edge", "이물", "particle", "비전 검사"],
    "고속 레이저 노칭 (>120 ppm)":     ["노칭", "notching", "탭 성형", "레이저 가공"],
    "Z-스태킹 고속화":                ["z-스태킹", "z stack", "지그재그", "zigzag", "적층"],
    "라미네이션 & 스태킹 (L&S)":        ["바이셀", "bicell", "라미네이션", "lamination", "스태킹"],
    "스택 정렬 실시간 비전 보정":        ["정렬", "alignment", "align", "적층 정렬", "위치 보정"],
    "초음파 탭 용접 품질 AI 판정":       ["초음파 용접", "ultrasonic weld", "탭 용접", "tab weld", "접합 강도"],
    "탭리스(Tabless) 젤리롤 와인딩":     ["탭리스", "tabless", "젤리롤", "jelly roll", "권취", "winding"],
    "46-시리즈 대형 원통 양산":         ["4680", "46파이", "원통형", "cylindrical", "대형 원통"],
    "진공 주액 사이클 최적화":          ["주액", "electrolyte filling", "함침", "impregnat", "진공 주입"],
    "케이스 레이저 용접 실시간 감시 (OCT)": ["oct", "용입", "penetration", "레이저 용접", "laser weld", "실시간 감시"],
    "셀 투 팩 직결 조립 (모듈리스)":     ["모듈리스", "module-less", "cell to pack", "셀투팩", "직결"],
    "파우치 딥드로잉 포밍":             ["딥드로잉", "deep draw", "파우치", "pouch", "성형"],
    "디게싱 자동화 라인":              ["디게싱", "degassing", "가스 제거", "재실링", "resealing"],
    "셀 외관 AI 검사 (멀티모달)":       ["외관 검사", "appearance", "실링부", "sealing", "초음파 검사"],
    "레이저 실링 (파우치)":            ["레이저 실링", "laser seal", "실링폭", "열판", "heat seal"],
    "SEI 형성 프로파일 정밀 제어":       ["sei", "피막", "formation protocol", "충전 프로파일", "전압 스텝", "초기 충전"],
    "OCV 편차 기반 불량 선별":          ["ocv", "개방회로전압", "open circuit voltage", "전압 편차", "선별"],
    "활성화 충방전 에너지 회생":         ["회생", "regenerat", "energy recovery", "전력 회수", "충방전기", "cycler"],
    "마이크로 단락 조기 검출":           ["미세 단락", "micro short", "내부 단락", "internal short", "이물 단락"],
    "활성화 챔버 온도 편차 제어":        ["챔버", "chamber", "온도 편차", "temperature uniform", "항온", "지그"],
    "버스바 레이저 용접":               ["버스바", "busbar", "bus bar", "접합 저항", "이종 금속"],
    "냉각판 일체형 브레이징":            ["브레이징", "brazing", "냉각판", "cooling plate", "유로", "cold plate"],
    "셀 간 방염·단열 패드 자동 적용":     ["방염", "단열 패드", "thermal barrier", "패드", "아에로겔", "aerogel", "mica"],
    "팩 기밀 자동 검사 (IP67)":         ["기밀", "leak test", "누설 검사", "ip67", "방수", "airtight"],
    "팩 EOL 통합 검사":                ["eol", "end of line", "출하 검사", "절연저항", "insulation resistance", "통합 검사"],
    "액침 냉각 구조":                  ["액침", "immersion", "침지", "유전체 냉매", "dielectric coolant", "직접 냉각"],
    "전극 탭 표면 클리닝":              ["클리닝", "cleaning", "산화층", "oxide layer", "플라즈마", "plasma", "표면 처리"],
    "젤리롤 프레싱·삽입":               ["프레싱", "pressing", "삽입", "insertion", "젤리롤", "캔 삽입"],
    "헬륨 리크 테스트 자동화":           ["헬륨", "helium", "리크", "leak", "추적 가스", "tracer gas"],
    "캡 어셈블리 자동 조립":             ["캡 어셈블리", "cap assembly", "안전벤트", "safety vent", "개스킷", "gasket"],
    "가스포켓 절단·재실링":             ["가스포켓", "gas pocket", "절단", "trimming", "재실링", "resealing", "2차 실링"],
    "소듐이온 배터리 양산":             ["소듐", "나트륨", "sodium", "sodium-ion", "sib", "na-ion", "钠离子"],
    "이종 케미스트리 복합 팩 (AB 시스템)": ["이종", "하이브리드 팩", "dual chemistry", "hybrid pack", "혼성", "soc 밸런싱", "balancing"],
    "초급속 충전 LFP (4C급)":          ["lfp", "인산철", "리튬인산철", "lithium iron phosphate", "급속 충전", "fast charging", "4c", "磷酸铁锂"],
    "반고체 고에너지 셀 (응축형)":       ["반고체", "semi-solid", "응축", "condensed", "고체 전해질", "solid electrolyte", "凝聚态"],
    "기술 라이선스 공급 (LRS)":         ["라이선스", "license", "licensing", "로열티", "royalty", "기술 이전"],
    "배터리 교환 서비스 (BaaS)":        ["교환", "swap", "swapping", "battery swap", "baas", "换电", "교체형"],
    "모듈리스 체적효율 극대화 (CTP 3.0)": ["체적 효율", "volume utilization", "ctp", "cell to pack", "모듈리스", "麒麟", "qilin"],
    "냉각·단열·구조 일체형 열관리":      ["수랭", "cooling plate", "일체형", "integrated", "단열", "크로스빔", "샌드위치", "sandwich"],
    "전 공정 폐루프 자율 보정":          ["폐루프", "closed loop", "closed-loop", "자율 보정", "피드백 제어", "feedback control", "리워크", "rework"],
    "십억분율 결함 관리 (DPB)":         ["결함률", "defect rate", "ppm", "dpb", "품질 관리", "quality control", "수율"],
    "엣지 AI 기반 초고속 택트":          ["택트", "tact time", "엣지", "edge ai", "로보틱스", "robotics", "자율 로봇"],
    "고전류 급속 활성화":               ["화성", "활성화", "formation", "급속 충전", "fast charg", "sei"],
    "가압 활성화 (Pressurized formation)": ["가압", "pressuriz", "가압 화성", "가압 활성화", "clamping"],
    "에이징 기간 단축 알고리즘":         ["에이징", "aging", "ocv", "숙성", "잔여 수명"],
    "활성화 데이터 기반 불량 예측 (AI)":   ["불량 예측", "defect predict", "내부단락", "internal short", "선별"],
    "고속 자가방전 선별 (μA급)":        ["자가방전", "self-discharge", "self discharge", "미세전류", "누설 전류"],
    "CTP (Cell to Pack)":            ["cell to pack", "셀투팩", "ctp", "모듈 없이", "팩 구조"],
    "CTC / CTB 차체 일체화":          ["ctc", "ctb", "cell to chassis", "차체 일체", "body integrat", "스케이트보드"],
    "구조용 접착 자동 도포":            ["구조용 접착", "structural adhesive", "접착제 도포", "dispens", "본딩"],
    "열폭주 전파 차단 구조":            ["열폭주", "thermal runaway", "전파 차단", "propagation", "차열"],
    "무선 BMS (wBMS)":               ["무선 bms", "wireless bms", "wbms", "무선 통신", "하네스"],
    "클라우드 BMS 진단·수명 예측":       ["수명 예측", "soh", "state of health", "클라우드", "원격 진단"],
    "화재 조기감지 센서 내장":           ["조기 감지", "early detect", "가스 센서", "gas sensor", "벤팅", "화재 감지"],
    "AMR 기반 무인 공정간 반송":        ["amr", "agv", "자율주행 로봇", "무인 반송", "autonomous mobile"],
    "전극 롤 자동 반송·보관":           ["롤 반송", "as-rs", "자동 창고", "roll handling", "무인 창고"],
    "물류 디지털 트윈 시뮬레이션":       ["디지털 트윈", "digital twin", "시뮬레이션", "simulation", "레이아웃"],
    "드라이룸 폐열회수 제습":           ["드라이룸", "dry room", "제습", "dehumidif", "폐열 회수"],
    "공정 폐열 재활용 네트워크":         ["폐열", "waste heat", "열 회수", "heat recovery", "열원"],
    "탄소배출 실시간 모니터링 (제품 LCA)": ["탄소발자국", "carbon footprint", "lca", "탄소배출", "배출량"],
    "재생에너지 직접 연계 운영":         ["재생에너지", "renewable", "ess", "태양광", "ppa", "전력 운영"],
    "모듈러 공장 공법":                ["모듈러", "modular", "표준 시공", "prefab", "공장 건설"],
    "Copy-Exact 표준 라인 패키지":      ["copy-exact", "표준 라인", "라인 복제", "standardiz"],
    "증설 리드타임 단축 공법":          ["증설", "리드타임", "lead time", "expansion", "캐파"],
}

# ── 배제 용어 — 있으면 그 기술이 아니다 ───────────────────────────────
NODE_EXCLUDE = {
    "무용매 PTFE 파이브릴화": ["의료", "medical", "필터", "membrane filter"],
    "레이저 슬리팅": ["용접", "welding"],
    "레이저 실링 (파우치)": ["슬리팅", "slitting", "노칭"],
    "무선 BMS (wBMS)": ["유선", "wired harness"],
}

GENERIC = {"전극", "배터리", "battery", "electrode", "이차전지", "cell", "셀",
           "리튬", "lithium", "secondary"}


def _cpc_list(ev: dict) -> list[str]:
    """근거에서 CPC/IPC 코드를 뽑는다. 소스마다 구분자가 다르다."""
    raw = (ev.get("cpc") or ev.get("ipc") or "")
    parts = re.split(r"[,|]", raw)
    return [p.strip().replace(" ", "").upper() for p in parts if p.strip()]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower())


def classify(ev: dict, node_names: list[str]) -> tuple[str | None, str, float, str]:
    """(노드 이름, 확신도, 점수, 판단 근거).

    확신도는 '확정' / '추정' / '관련' / '미배정'.
    """
    codes = _cpc_list(ev)
    text = _norm(" ".join([ev.get("ref", ""), ev.get("summary", ""),
                           " ".join(ev.get("keywords") or [])]))

    best, best_score, best_why, best_conf = None, 0.0, "", "미배정"
    for name in node_names:
        cpcs = NODE_CPC.get(name, [])
        terms = NODE_TERMS.get(name, [])
        excl = NODE_EXCLUDE.get(name, [])

        if any(x in text for x in excl):
            continue

        hit_cpc = [c for c in cpcs
                   if any(code.startswith(c.replace(" ", "").upper()) for code in codes)]
        hit_terms = [t for t in terms if t.lower() in text and t.lower() not in GENERIC]

        score = len(hit_cpc) * 6.0 + len(hit_terms) * 3.0
        if not score:
            continue

        if hit_cpc and hit_terms:
            conf = "확정"
        elif len(hit_terms) >= 2 or (hit_cpc and len(hit_cpc) >= 2):
            conf = "추정"
        else:
            conf = "관련"

        if score > best_score:
            parts = []
            if hit_cpc:
                parts.append("CPC " + "·".join(hit_cpc[:3]))
            if hit_terms:
                parts.append("용어 " + "·".join(hit_terms[:3]))
            best, best_score, best_why, best_conf = name, score, " + ".join(parts), conf

    return best, best_conf, round(best_score, 1), best_why


def stats_header() -> str:
    return ("판독 근거: CPC/IPC 국제분류 + 특징 용어 + 배제 용어. "
            "확정·추정만 판정에 사용하고 관련은 참고로만 둔다.")
