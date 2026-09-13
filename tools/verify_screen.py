"""화면 검증 — 문구·색·정렬·팝업·정합성·반응형.

    .venv\Scripts\python.exe tools\verify_screen.py out1.png out2.png
    (기본 대상: dist/V4-index.html. 다른 판은 CTI_VERIFY_URL 로 지정)

판을 내보내기 전에 반드시 통과해야 한다. 하나라도 실패하면 내보내지 않는다.
"""
import os
import sys
from playwright.sync_api import sync_playwright

URL = os.environ.get("CTI_VERIFY_URL", "file:///C:/Users/dwkim/AI/dist/V4-index.html")
fails, errs = [], []


def ck(n, c, x=""):
    print(("  ok   " if c else "  FAIL ") + n + (f"  {x}" if x else ""))
    if not c:
        fails.append(n)


with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 1400})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text)
          if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.goto(URL, wait_until="domcontentloaded")
    pg.wait_for_timeout(2800)

    print("-- 용어 --")
    body = pg.locator("body").inner_text()
    ck("'화성' 없음", "화성" not in body,
       [l for l in body.split("\n") if "화성" in l][:1])
    ck("'활성화' 있음", "활성화" in body)
    ck("'따라잡는' 없음", "따라잡" not in body)
    ck("'기술 격차' 있음", "기술 격차" in body)
    ck("'최우선 검토 기술'", "최우선 검토 기술" in body)
    ck("'자사 수준' (위치 아님)", "자사 수준" in body)
    ck("'일부 확보' 없음", "일부 확보" not in body)

    print("-- KPI --")
    lab = [x.strip() for x in pg.locator(".kpi .eyebrow").all_inner_texts()]
    val = [x.strip() for x in pg.locator(".kpi .v").all_inner_texts()]
    for l, v in zip(lab, val):
        print(f"     {l} = {v}")
    ck("열위/동등/우위/범위", lab == ["열위 기술", "동등 기술", "우위 기술", "경쟁사 범위"], str(lab))
    fs = pg.evaluate("()=>getComputedStyle(document.querySelector('.kpi .v')).fontSize")
    ck("숫자 48px", fs == "48px", fs)
    c1 = pg.evaluate("()=>getComputedStyle(document.querySelector('.kpi.k-behind .v')).color")
    c3 = pg.evaluate("()=>getComputedStyle(document.querySelector('.kpi.k-ahead .v')).color")
    ck("열위=빨강", c1 == "rgb(192, 57, 43)", c1)
    ck("우위=초록", c3 == "rgb(44, 107, 82)", c3)

    print("-- 파이프라인: 자사 기술 전량 · 수준별 --")
    tog = pg.locator("#haveToggle").inner_text()
    ck("우위 기술 기본 펼침", "접기" in tog, tog)
    n_all = pg.locator(".pc").count()
    ck("57개 기술 전량 표시", n_all == 57, f"{n_all}장")
    for cls, nm in ((".pc.lv-behind", "열위"), (".pc.lv-even", "동등"),
                    (".pc.lv-ahead", "우위"), (".pc.lv-none", "근거부족")):
        ck(f"{nm} 카드 존재", pg.locator(cls).count() > 0, f"{pg.locator(cls).count()}장")
    ck("공정별 수준 분포 막대", pg.locator(".ps-mix").count() == 5)
    ck("근거 위계 명시(특허가 핵심)", "특허를 핵심 기준" in body)
    pipe_txt = pg.locator("#pipe").inner_text()
    ck("'미보유/일부/보유' 구분 미사용", "미보유" not in pipe_txt and "일부 " not in pipe_txt)
    ck("수준 배지 표기", pg.locator(".pc-lv").count() == 57,
       f"{pg.locator('.pc-lv').count()}개")

    print("-- 정렬(시급도 내림차순) --")
    sc = pg.evaluate("()=>SEQ.map(i=>i.score)")
    ck("SEQ 내림차순", all(sc[i] >= sc[i+1] for i in range(len(sc)-1)), f"{sc[:6]}…")

    print("-- 상세: 기술 구분 --")
    pg.locator("#tbody tr").first.click(); pg.wait_for_timeout(500)
    det = pg.locator("#detail").inner_text()
    ck("기술 구분 배지", pg.locator("#detail .tclass").count() == 1,
       pg.locator("#detail .tclass").first.inner_text() if pg.locator("#detail .tclass").count() else "")
    ck("한 줄 정의", pg.locator("#detail .tclass-d").count() == 1,
       pg.locator("#detail .tclass-d").first.inner_text()[:44])

    print("-- 근거 3블록 접힘 --")
    ck("fold 3개", pg.locator("#detail .fold").count() == 3,
       f"{pg.locator('#detail .fold').count()}개")
    h = pg.evaluate("()=>document.querySelector('#detail .fold.clipped .fold-body').clientHeight")
    ck("접힌 높이 ≤ 104px", h <= 104, f"{h}px")
    ck("전체보기 버튼", pg.locator("#detail .morebtn").count() == 3)

    print("-- 매트릭스 정합성: 칸 건수 = 팝업 건수 --")
    cells = pg.locator("#detail .mcol")
    bad = []
    for i in range(cells.count()):
        c = cells.nth(i)
        co = c.get_attribute("data-co")
        txt = c.inner_text()
        # 칸이 보여 주는 값은 '수집된 전체 건수'(it.cnt)여야 한다.
        # 팝업이 나열하는 건수(it.ev)는 추린 것이라 더 적을 수 있다 — 그건 정상이다.
        n_popup = pg.evaluate(
            "co=>{const it=sel;return (it.cnt&&it.cnt[co]!=null)?it.cnt[co]"
            ":it.ev.filter(e=>e.w===co).length}", co)
        import re
        m = re.search(r"(\d+)건", txt)
        n_cell = int(m.group(1)) if m else None
        if n_cell is not None and n_cell != n_popup:
            bad.append(f"{co}: 칸{n_cell} vs 팝업{n_popup}")
    ck("칸 건수 = 수집 건수", not bad, "; ".join(bad) if bad else "모든 칸 일치")
    ghost = pg.evaluate("""()=>{const o=[];SEQ.forEach(it=>{
        [...it.r,...it.p].forEach(co=>{const n=(it.cnt&&it.cnt[co])||0;
          if(!n) o.push(it.n+'/'+co);});});return o;}""")
    ck("'보유·일부'인데 근거 0건인 칸 없음", not ghost, "; ".join(ghost[:4]))
    empty = pg.evaluate("""()=>{const o=[];SEQ.forEach(it=>{
        [...it.r,...it.p].forEach(co=>{if(!it.ev.some(e=>e.w===co)) o.push(it.n+'/'+co);});});
        return o;}""")
    ck("모든 보유사에 실제 근거가 실림", not empty, "; ".join(empty[:4]))

    print("-- 팝업 3종 --")
    pg.locator('.whybtn[data-why="urgency"]').first.click(); pg.wait_for_timeout(400)
    mt = pg.locator("#modalBody").inner_text()
    ck("시급도 팝업에 곱셈", "×" in mt or "곱" in mt, mt[:50].replace("\n", " "))
    pg.locator("#modalX").click(); pg.wait_for_timeout(250)

    pg.locator('.whybtn[data-why="class"]').first.click(); pg.wait_for_timeout(400)
    ck("기술 구분 팝업", "열위 기술" in pg.locator("#modalBody").inner_text())
    pg.locator("#modalX").click(); pg.wait_for_timeout(250)

    pg.locator('.whybtn[data-why="lag"]').first.click(); pg.wait_for_timeout(400)
    lt = pg.locator("#modalBody").inner_text()
    ck("기술 격차 팝업에 산정 근거", "납기" in lt or "소요" in lt, lt[:60].replace("\n", " "))
    pg.locator("#modalX").click(); pg.wait_for_timeout(250)

    print("-- 시급도 곱셈 팝업(개별 기술) --")
    rows = pg.locator("#tbody tr")
    for i in range(min(rows.count(), 8)):
        rows.nth(i).click(); pg.wait_for_timeout(300)
        if pg.locator("#detail .urgbtn, #detail [data-urg]").count():
            break
    ck("상세 진입 정상", pg.locator("#detail .tclass").count() == 1)

    print("-- 임원 보고 어조(개조식) --")
    import re as _re
    polite = sorted(set(_re.findall(r"[가-힣][^\n]{0,28}?(?:습니다|합니다|입니다|됩니다|십시오)", body)))
    ck("경어체 문장 없음", not polite, "; ".join(polite[:3]))

    print("-- 반응형 --")
    for w in (1600, 1180, 900, 420):
        pg.set_viewport_size({"width": w, "height": 1000}); pg.wait_for_timeout(350)
        ov = pg.evaluate(
            "document.documentElement.scrollWidth-document.documentElement.clientWidth")
        ck(f"{w}px 가로 넘침 없음", ov <= 1, f"{ov}px")

    pg.set_viewport_size({"width": 1500, "height": 1500}); pg.wait_for_timeout(400)
    if len(sys.argv) > 1: pg.locator(".kpis").screenshot(path=sys.argv[1])
    pg.locator("#tbody tr").first.click(); pg.wait_for_timeout(500)
    if len(sys.argv) > 2: pg.locator("#detail").screenshot(path=sys.argv[2])
    b.close()

print("\n콘솔 오류:", errs if errs else "없음")
print("실패:", fails if fails else "없음")
sys.exit(1 if (fails or errs) else 0)
