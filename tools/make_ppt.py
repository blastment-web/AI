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
         space=0):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    first = True
    for item in runs:
        s, size, color, bold = (list(item) + [False])[:4]
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
         + ("AI 판독: CPC 국제분류 규칙" if VER == "V4" else "AI 판독: 규칙 + LLM 재판독")
         + "   |   2026-09-13 실측 기준", 11, MUTED)])
    box(s, M, Inches(1.06), CW, Pt(1.5), fill=INK)

    # ── 흐름 5단계 ─────────────────────────────────────────────
    fy = Inches(1.22)
    fh = Inches(1.02)
    flow = [
        ("① 조사 범위", "1억 7,041만 건", "전 세계 특허 문헌", INK),
        ("② 수집 완료", "4만 2,289 건", "특허 4만 1,665 · 공시 590 · 논문 34", GREEN),
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
        "기술 격차를 단계별 수행 과업 및 소요기간으로 분해 제시함",
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
        "기존 '미보유' 18건 전량에서 자사 특허 검색됨 — 공정기술팀 재검증 필요함",
        "특허가족 병합 미적용 — 동일 발명의 국가별 중복 계상 발생함",
        "BYD 설비투자 원천 부재 확인 · 파나소닉은 EDINET 키 발급 필요함",
        "경쟁사 근거는 특허 중심 — 라인 가동 여부 미확인 상태임",
    ]
    for i, t in enumerate(limits):
        text(s, Emu(int(rx + Inches(0.16))), Emu(int(y2 + Inches(0.42) + i * Inches(0.26))),
             Emu(int(rw - Inches(0.32))), Inches(0.24),
             [("· " + t, 9.5, INK2)])

    # ── 하단: 다음 단계 ────────────────────────────────────────
    by = Inches(5.72)
    bh = Inches(1.32)
    steps = [
        ("완료", "창구 6곳 연결 · 판정 기준 재정립",
         "SEC·HKEX·학회 신규 연결 완료.\n시급도 곱셈 방식 전환 적용.", "추가 비용 없음", GREEN),
        ("1단계", "자사 보유 현황 확정",
         "'미보유' 18건 재검증 추진.\n공정기술팀 확인 필요함.", "약 3일", AMBER),
        ("2단계", "특허가족·법인명 병합",
         "중복 계상 제거를 통한\n집계 신뢰도 확보.", "약 2일", AMBER),
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

    prs.save(OUT)
    print(f"생성 완료: {OUT}")


if __name__ == "__main__":
    main()
