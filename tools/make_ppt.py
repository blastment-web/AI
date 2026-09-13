"""임원 보고용 1장 PPT 생성.

목적: 이 한 장만 봐도 (1) 정보가 어디서 얼마나 오는지 (2) 지금 완성도가 얼마인지
(3) 임원에게 무슨 판단을 도와주는지 (4) 한계가 무엇인지를 알 수 있게 한다.
숫자는 전부 2026-09-12 실측값이다.
"""
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

OUT = sys.argv[1] if len(sys.argv) > 1 else "경쟁기술_인텔리전스_구조.pptx"
VER = sys.argv[2] if len(sys.argv) > 2 else "V4"

INK    = RGBColor(0x14, 0x18, 0x1C)
INK2   = RGBColor(0x41, 0x4A, 0x52)
MUTED  = RGBColor(0x79, 0x83, 0x8C)
MARK   = RGBColor(0xE5, 0x00, 0x7D)
AMBER  = RGBColor(0xB9, 0x82, 0x1A)
GREEN  = RGBColor(0x2C, 0x6B, 0x52)
RULE   = RGBColor(0xD6, 0xDB, 0xDF)
SOFT   = RGBColor(0xEF, 0xF1, 0xF2)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
PANEL  = RGBColor(0xFA, 0xFB, 0xFB)

F = "맑은 고딕"


def box(slide, x, y, w, h, fill=None, line=None, lw=0.75):
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    sh.shadow.inherit = False
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(lw)
    sh.text_frame.word_wrap = True
    return sh


def text(slide, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
         space=0, inline=False):
    """runs 를 텍스트 상자에 넣는다.

    기본은 run 하나가 한 줄이다. inline=True 면 전부 한 단락에 이어 붙인다
    — 색이 다른 꼬리표를 한 줄에 두려면 이 쪽을 써야 한다. 나누어 넣으면
    줄바꿈되어 아래 요소와 겹친다.
    """
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    first = True
    for item in runs:
        s, size, color, bold = (list(item) + [False])[:4]
        if inline and not first:
            p = tf.paragraphs[-1]
        else:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = align
        p.space_after = Pt(space)
        r = p.add_run()
        r.text = s
        r.font.size = Pt(size)
        r.font.color.rgb = color
        r.font.bold = bold
        r.font.name = F
    return tb


def bar(slide, x, y, w, h, pct, color):
    box(slide, x, y, w, h, fill=RGBColor(0xED, 0xF0, 0xF1))
    if pct > 0:
        box(slide, x, y, Emu(int(w * pct / 100)), h, fill=color)


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[6])

    W = Inches(13.333)
    M = Inches(0.42)
    CW = W - 2 * M                      # 콘텐츠 폭

    # 배경
    box(s, 0, 0, W, prs.slide_height, fill=SOFT)

    # ── 제목 ───────────────────────────────────────────────────
    text(s, M, Inches(0.30), CW, Inches(0.5), [
        (f"경쟁기술 인텔리전스 {VER} — 자사 기술 수준 진단 및 보완 우선순위", 24, INK, True)])
    text(s, M, Inches(0.76), CW, Inches(0.3), [
        ("특허를 핵심 기준으로 판정, 설비투자 공시·기술발표를 보조 근거로 교차 검증함   |   "
         # 판독기는 판 이름이 아니라 실제 엔진을 따른다. V5 만 LLM 재판독을 얹는다.
         + ("AI 판독: 규칙 + LLM 재판독" if VER.upper() == "V5"
            else "AI 판독: CPC 국제분류 규칙")
         + "   |   2026-09-13 실측 기준", 11, MUTED)])
    box(s, M, Inches(1.06), CW, Pt(1.5), fill=INK)

    # ── 흐름 5단계 ─────────────────────────────────────────────
    fy = Inches(1.22)
    fh = Inches(1.02)
    flow = [
        ("① 조사 범위", "1억 7,041만 건", "전 세계 특허 문헌", INK),
        ("② 패밀리 병합", "2만 2,452 건", "특허 4만 1,665건의 국가별 중복 제거분", GREEN),
        ("③ 기술 배정", "1만 1,060 건", "CPC 국제분류 판독 적용", GREEN),
        ("④ 판정 기술", "54 / 57 개", "근거 확보 기술 수", GREEN),
        ("⑤ 완성도", "약 80 %", "창구 6곳 연결 완료", AMBER),
    ]
    gap = Inches(0.09)
    fw = Emu(int((CW - gap * (len(flow) - 1)) / len(flow)))
    for i, (label, val, desc, col) in enumerate(flow):
        x = Emu(int(M + i * (fw + gap)))
        box(s, x, fy, fw, fh, fill=WHITE, line=RULE)
        text(s, Emu(int(x + Inches(0.14))), Emu(int(fy + Inches(0.11))),
             Emu(int(fw - Inches(0.28))), Inches(0.2), [(label, 9.5, MUTED)])
        text(s, Emu(int(x + Inches(0.14))), Emu(int(fy + Inches(0.32))),
             Emu(int(fw - Inches(0.28))), Inches(0.34), [(val, 19, col, True)])
        text(s, Emu(int(x + Inches(0.14))), Emu(int(fy + Inches(0.70))),
             Emu(int(fw - Inches(0.28))), Inches(0.26), [(desc, 8.5, INK2)])
        if i < len(flow) - 1:
            ar = s.shapes.add_shape(MSO_SHAPE.ISOSCELES_TRIANGLE,
                                    Emu(int(x + fw + Inches(0.005))),
                                    Emu(int(fy + fh / 2 - Inches(0.06))),
                                    Inches(0.08), Inches(0.12))
            ar.rotation = 90
            ar.fill.solid(); ar.fill.fore_color.rgb = MUTED
            ar.line.fill.background(); ar.shadow.inherit = False

    # ── 좌: 원천별 현황 ─────────────────────────────────────────
    ly = Inches(2.46)
    lw = Emu(int(CW * 0.50))
    lh = Inches(3.12)
    box(s, M, ly, lw, lh, fill=WHITE, line=RULE)
    text(s, Emu(int(M + Inches(0.16))), Emu(int(ly + Inches(0.13))),
         Emu(int(lw - Inches(0.3))), Inches(0.24),
         [("경쟁사별 조사 규모", 12.5, INK, True)])

    GREY = RGBColor(0xB6, 0xBD, 0xC3)
    sources = [
        ("자사 (LGES)", "특허 1만 5,990 · 공시 79", "1만 6,069", 100, MARK),
        ("CATL", "특허 9,826 · 설비투자 공시 27", "9,853", 61, GREEN),
        ("삼성SDI", "특허 6,717 · 공시 82", "6,799", 42, GREEN),
        ("파나소닉", "특허 2,991 · 공시 1 — EDINET 미연결", "2,992", 19, AMBER),
        ("SK온", "특허 2,261 · 공시 62", "2,323", 14, GREEN),
        ("BYD", "특허 2,215 · 설비투자 원천 부재 확인", "2,222", 14, AMBER),
        ("테슬라", "특허 169 · SEC 본문검색 연결", "169", 2, AMBER),
        ("합계", "경쟁사 6사 + 자사", "4만 2,289", 100, INK),
    ]
    ry = ly + Inches(0.46)
    rh = Inches(0.325)
    for i, (name, desc, vol, pct, col) in enumerate(sources):
        y = Emu(int(ry + i * rh))
        box(s, Emu(int(M + Inches(0.16))), Emu(int(y + Inches(0.115))),
            Inches(0.075), Inches(0.075), fill=col)
        # 좌표는 패널 안쪽(M ~ M+6.09")에 전부 들어와야 한다.
        # 넘치면 오른쪽 박스에 가려져 % 숫자가 사라진다.
        text(s, Emu(int(M + Inches(0.30))), Emu(int(y + Inches(0.03))),
             Inches(1.15), Inches(0.2), [(name, 10, INK, True)])
        text(s, Emu(int(M + Inches(1.50))), Emu(int(y + Inches(0.04))),
             Inches(2.45), Inches(0.2), [(desc, 8, MUTED)])
        text(s, Emu(int(M + Inches(3.98))), Emu(int(y + Inches(0.03))),
             Inches(0.95), Inches(0.2), [(vol, 9.5, INK if pct else MUTED, bool(pct))],
             align=PP_ALIGN.RIGHT)
        bar(s, Emu(int(M + Inches(5.00))), Emu(int(y + Inches(0.10))),
            Inches(0.72), Inches(0.085), pct, col)
        text(s, Emu(int(M + Inches(5.76))), Emu(int(y + Inches(0.03))),
             Inches(0.33), Inches(0.2), [(f"{pct}%", 9, INK2, True)], align=PP_ALIGN.RIGHT)

    # ── 우: 무엇을 도와주는가 / 한계 ────────────────────────────
    rx = Emu(int(M + lw + Inches(0.16)))
    rw = Emu(int(CW - lw - Inches(0.16)))

    h1 = Inches(1.52)
    box(s, rx, ly, rw, h1, fill=WHITE, line=RULE)
    text(s, Emu(int(rx + Inches(0.16))), Emu(int(ly + Inches(0.13))),
         Emu(int(rw - Inches(0.32))), Inches(0.22),
         [("의사결정 지원 항목", 12.5, INK, True)])
    helps = [
        "공정기술 57개 전량을 열위 16 · 동등 14 · 우위 20 으로 구분 제시함",
        "시급도 = 기술 격차 × 경쟁사 확산도 × 근거 확실성 — 보완 우선순위 도출",
        "기술 격차를 특허·공시·발표 3축 대리 지표로 추정, 기준·보수 듀얼 트랙 제시함",
        "전 수치에 근거 목록 및 원문 링크 연결 — 원천까지 역추적 가능함",
    ]
    for i, t in enumerate(helps):
        text(s, Emu(int(rx + Inches(0.16))), Emu(int(ly + Inches(0.42) + i * Inches(0.26))),
             Emu(int(rw - Inches(0.32))), Inches(0.24),
             [("· " + t, 9.5, INK2)])

    h2 = Inches(1.52)
    y2 = Emu(int(ly + h1 + Inches(0.08)))
    box(s, rx, y2, rw, h2, fill=WHITE, line=MARK, lw=1.25)
    text(s, Emu(int(rx + Inches(0.16))), Emu(int(y2 + Inches(0.13))),
         Emu(int(rw - Inches(0.32))), Inches(0.22),
         [("한계 및 후속 과제", 12.5, MARK, True)])
    limits = [
        "경쟁사 수율·제조원가 비공개 — 본 모델 산출 대상에서 명시적 제외함",
        "기존 '미보유' 18건 전량에서 자사 특허 검색됨 — 공정기술팀 재검증 필요함",
        "설비투자 공시가 공정기술 단위로 미배정 — 신뢰도 '상' 판정 0건 사유임",
        "BYD 설비투자 원천 부재 확인 · 파나소닉은 EDINET 키 발급 필요함",
    ]
    for i, t in enumerate(limits):
        text(s, Emu(int(rx + Inches(0.16))), Emu(int(y2 + Inches(0.42) + i * Inches(0.26))),
             Emu(int(rw - Inches(0.32))), Inches(0.24),
             [("· " + t, 9.5, INK2)])

    # ── 하단: 다음 단계 ────────────────────────────────────────
    by = Inches(5.72)
    bh = Inches(1.32)
    steps = [
        ("완료", "3축 격차 추정 모델 적용",
         "패밀리 병합 4.2만→2.2만건.\n보정 계수·듀얼 트랙 적용 완료.", "추가 비용 없음", GREEN),
        ("1단계", "자사 보유 현황 확정",
         "'미보유' 18건 재검증 추진.\n공정기술팀 확인 필요함.", "약 3일", AMBER),
        ("2단계", "공시 본문 확보 — 축 2 가동",
         "투자 규모·준공 시점 추출로\n신뢰도 '상' 판정 확보.", "약 2일", AMBER),
        ("3단계", "EDINET·EPO 연결",
         "파나소닉 설비투자 및 청구항 원문.\n키 발급 후 즉시 적용 가능함.", "약 2일", AMBER),
    ]
    gap2 = Inches(0.11)
    bw = Emu(int((CW - gap2 * (len(steps) - 1)) / len(steps)))
    for i, (tag, title, desc, cost, col) in enumerate(steps):
        x = Emu(int(M + i * (bw + gap2)))
        box(s, x, by, bw, bh, fill=WHITE, line=RULE)
        box(s, x, by, Pt(3), bh, fill=col)
        text(s, Emu(int(x + Inches(0.18))), Emu(int(by + Inches(0.11))),
             Emu(int(bw - Inches(0.3))), Inches(0.18), [(tag, 8.5, MUTED)])
        text(s, Emu(int(x + Inches(0.18))), Emu(int(by + Inches(0.30))),
             Emu(int(bw - Inches(0.3))), Inches(0.24), [(title, 12, INK, True)])
        text(s, Emu(int(x + Inches(0.18))), Emu(int(by + Inches(0.60))),
             Emu(int(bw - Inches(0.3))), Inches(0.46), [(desc, 8.5, INK2)])
        text(s, Emu(int(x + Inches(0.18))), Emu(int(by + Inches(1.06))),
             Emu(int(bw - Inches(0.3))), Inches(0.2), [(cost, 9, col, True)])

    # ── 꼬리말 ────────────────────────────────────────────────
    text(s, M, Inches(7.16), CW, Inches(0.22), [
        ("전 수치는 2026-09-13 실측값이며, 추정치는 '약'으로 표기함.   |   "
         "LG에너지솔루션 기술전략 · 내부 검토용", 8, MUTED)])

    model_slide(prs)

    prs.save(OUT)
    print(f"생성 완료: {OUT}")


def model_slide(prs):
    """2장 — 특허·공시·기술발표 기반 기술 격차 추정 모델 개요.

    임원 질의("수율도 모르면서 어떻게 산출했는가")에 대한 방어 논리를 장표로 고정한다.
    """
    s = prs.slides.add_slide(prs.slide_layouts[6])
    W = prs.slide_width
    M = Inches(0.62)
    CW = Emu(int(W - 2 * M))

    box(s, 0, 0, W, Inches(0.06), fill=INK)
    text(s, M, Inches(0.34), CW, Inches(0.3),
         [("기술 격차 추정 모델 개요", 23, INK, True)])
    text(s, M, Inches(0.76), CW, Inches(0.26),
         [("특허·설비투자 공시·대외 기술발표 3축 대리 지표 결합 방식   |   "
           "경쟁사 수율·제조원가는 비공개로 산출 대상에서 제외함", 11, MUTED)])

    # ── 산식 ─────────────────────────────────────────────────
    fy = Inches(1.24)
    box(s, M, fy, CW, Inches(0.62), fill=SOFT, line=RULE)
    text(s, Emu(int(M + Inches(0.22))), Emu(int(fy + Inches(0.16))),
         Emu(int(CW - Inches(0.44))), Inches(0.3),
         [("기술 격차 = 실행 소요기간 × 3축 관측 보정 계수 × 불확실성 여유",
           15, INK, True)])

    # ── 3축 ──────────────────────────────────────────────────
    ay = Inches(2.06)
    ah = Inches(1.78)
    axes = [
        ("축 1 · 특허", "R&D 선행 격차", "가중 55%",
         "패밀리 병합 후 선점 시점 격차와\n품질 가중 출원량을 개월로 환산함.\n"
         "국가 수·등록 여부·최신성 반영함.", "가동 중 · 50개 기술", GREEN),
        ("축 2 · 공시", "양산 진입 격차", "가중 30%",
         "투자 규모·준공 시점으로 SOP\n진입 시점을 추정함.\n"
         "일정 지연 계수 1.35 적용함.", "본문 확보 필요", AMBER),
        ("축 3 · 발표", "스펙 수준 격차", "가중 15%",
         "발표 목표 스펙과 자사 현행\n스펙의 성능 갭을 환산함.\n"
         "마케팅 보정 0.75 적용함.", "표본 확대 필요", AMBER),
    ]
    gap = Inches(0.14)
    aw = Emu(int((CW - gap * 2) / 3))
    for i, (tag, title, w, desc, state, col) in enumerate(axes):
        x = Emu(int(M + i * (aw + gap)))
        box(s, x, ay, aw, ah, fill=WHITE, line=RULE)
        box(s, x, ay, aw, Pt(3), fill=col)
        # 가중치는 꼬리표 줄에 붙인다. 제목 줄에 함께 두면 줄바꿈되어 본문과 겹친다.
        text(s, Emu(int(x + Inches(0.18))), Emu(int(ay + Inches(0.16))),
             Emu(int(aw - Inches(0.36))), Inches(0.2),
             [(tag + "   ", 9, MUTED), (w, 9, col, True)], inline=True)
        text(s, Emu(int(x + Inches(0.18))), Emu(int(ay + Inches(0.38))),
             Emu(int(aw - Inches(0.36))), Inches(0.26),
             [(title, 13, INK, True)])
        text(s, Emu(int(x + Inches(0.18))), Emu(int(ay + Inches(0.70))),
             Emu(int(aw - Inches(0.36))), Inches(0.78), [(desc, 9.5, INK2)])
        text(s, Emu(int(x + Inches(0.18))), Emu(int(ay + Inches(1.48))),
             Emu(int(aw - Inches(0.36))), Inches(0.2), [(state, 9, col, True)])

    # ── 듀얼 트랙 ────────────────────────────────────────────
    dy = Inches(4.04)
    dh = Inches(1.18)
    dw = Emu(int((CW - gap) / 2))
    duals = [
        ("기준 시나리오 (Base)", "공시·발표에 보정 계수 적용분",
         "마케팅성 과장 및 일정 지연을 차감한 값임.\n보완 투자 의사결정의 기준선으로 적용함.", INK),
        ("보수 시나리오 (Conservative)", "공시·발표 액면가 수용분",
         "경쟁사 발표가 전량 실행될 경우의 값임.\n"
         "기준값과의 차이는 발표 의존도를 의미함.", MARK),
    ]
    for i, (t, sub, d, col) in enumerate(duals):
        x = Emu(int(M + i * (dw + gap)))
        box(s, x, dy, dw, dh, fill=WHITE, line=col, lw=1.25)
        text(s, Emu(int(x + Inches(0.2))), Emu(int(dy + Inches(0.14))),
             Emu(int(dw - Inches(0.4))), Inches(0.24), [(t, 12.5, col, True)])
        text(s, Emu(int(x + Inches(0.2))), Emu(int(dy + Inches(0.42))),
             Emu(int(dw - Inches(0.4))), Inches(0.2), [(sub, 9.5, MUTED)])
        text(s, Emu(int(x + Inches(0.2))), Emu(int(dy + Inches(0.66))),
             Emu(int(dw - Inches(0.4))), Inches(0.44), [(d, 9.5, INK2)])

    # ── 방어 논리 ────────────────────────────────────────────
    vy = Inches(5.42)
    box(s, M, vy, CW, Inches(1.5), fill=WHITE, line=INK, lw=1.25)
    text(s, Emu(int(M + Inches(0.22))), Emu(int(vy + Inches(0.14))),
         Emu(int(CW - Inches(0.44))), Inches(0.24),
         [("예상 질의 대응 — \"수율·양산 데이터 없이 신뢰 가능한가\"", 12.5, INK, True)])
    defense = [
        "본 수치는 경쟁사 절대 진도가 아닌, 검증 가능한 공개 근거상의 상대 격차임. "
        "수율·원가는 산출 대상에서 명시적으로 제외하였음.",
        "발표·공시는 액면가 미반영함. 마케팅 보정 0.75 및 일정 지연 1.35 적용 기준값과 "
        "액면가 수용 보수값을 병행 제시하며, 양자 차이를 발표 의존도로 표기함.",
        "전 수치는 원문까지 역추적 가능하며, 근거 부족 건은 '판정 불가'로 분리 표기함. "
        "현 신뢰도 '상' 판정 0건으로 확인 범위를 초과하여 주장하지 않음.",
    ]
    for i, t in enumerate(defense):
        text(s, Emu(int(M + Inches(0.22))), Emu(int(vy + Inches(0.44) + i * Inches(0.33))),
             Emu(int(CW - Inches(0.44))), Inches(0.3),
             [(f"{i+1}. " + t, 9.5, INK2)])

    text(s, M, Inches(7.16), CW, Inches(0.22), [
        ("보정 계수는 업계 통상치 적용분이며, 사내 실적 데이터 확보 시 해당 값으로 대체 "
         "적용 예정임.   |   LG에너지솔루션 기술전략 · 내부 검토용", 8, MUTED)])


if __name__ == "__main__":
    main()
