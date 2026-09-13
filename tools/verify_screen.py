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
    ck("KPI 라벨 6종(수준 5 + 경쟁사)",
       lab == ["열위 기술", "동등 기술", "우위 기술", "확인 필요", "근거 부족", "경쟁사 범위"],
       str(lab))
    fs = pg.evaluate("()=>getComputedStyle(document.querySelector('.kpi .v')).fontSize")
    ck("KPI 숫자 48px 이상", float(fs.replace("px", "")) >= 48, fs)
    c1 = pg.evaluate("()=>getComputedStyle(document.querySelector('.kpi.k-behind .v')).color")
    c3 = pg.evaluate("()=>getComputedStyle(document.querySelector('.kpi.k-ahead .v')).color")
    ck("열위=빨강", c1 == "rgb(192, 57, 43)", c1)
    ck("우위=초록", c3 == "rgb(44, 107, 82)", c3)

    print("-- 파이프라인: 자사 기술 전량 · 수준별 --")
    tog = pg.locator("#haveToggle").inner_text()
    ck("우위 기술 기본 펼침", "접기" in tog, tog)
    n_all = pg.locator(".pc").count()
    # SEQ 는 window 에 노출되지 않는다. 판정 결과 파일과 직접 대조한다.
    import json as _json
    from pathlib import Path as _Path
    _tree = _json.loads((_Path(__file__).resolve().parent.parent
                         / "data" / "tree.json").read_text(encoding="utf-8"))
    n_seq = len(_tree["nodes"])
    ck("기술 전량 표시(판정 결과와 일치)", n_all == n_seq, f"카드 {n_all} / 데이터 {n_seq}")
    for cls, nm in ((".pc.lv-behind", "열위"), (".pc.lv-even", "동등"),
                    (".pc.lv-ahead", "우위"), (".pc.lv-hold", "확인 필요"),
                    (".pc.lv-none", "근거부족")):
        ck(f"{nm} 카드 존재", pg.locator(cls).count() > 0, f"{pg.locator(cls).count()}장")
    # 수준 구분이 서로를 잡아먹지 않는지 — 합이 전체와 같아야 한다
    parts = sum(pg.locator(c).count() for c in
                (".pc.lv-behind", ".pc.lv-even", ".pc.lv-ahead",
                 ".pc.lv-hold", ".pc.lv-none"))
    ck("수준 구분 합 = 전체", parts == n_all, f"{parts} / {n_all}")
    ck("공정별 수준 분포 막대", pg.locator(".ps-mix").count() == 5)
    ck("근거 위계 명시(특허가 핵심)", "특허를 핵심 기준" in body)
    pipe_txt = pg.locator("#pipe").inner_text()
    ck("'미보유/일부/보유' 구분 미사용", "미보유" not in pipe_txt and "일부 " not in pipe_txt)
    ck("수준 배지 표기", pg.locator(".pc-lv").count() == n_all,
       f"{pg.locator('.pc-lv').count()} / {n_all}")

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

    print("-- V6 시인성: 작은 글씨가 없어야 한다 --")
    tiny = pg.evaluate("""() => {
      const bad = [];
      document.querySelectorAll('body *').forEach(el => {
        if (!el.offsetParent && el.tagName !== 'BODY') return;
        const t = (el.textContent || '').trim();
        if (!t || el.children.length) return;
        const px = parseFloat(getComputedStyle(el).fontSize);
        if (px < 11.5) bad.push(px + 'px: ' + t.slice(0, 24));
      });
      return bad.slice(0, 6);
    }""")
    ck("본문 글자 11.5px 미만 없음", not tiny, "; ".join(tiny))

    gutter = pg.evaluate(
        "() => getComputedStyle(document.querySelector('.wrap')).paddingLeft")
    ck("좌우 여백 절반 축소(28px → 14px)", gutter == "14px", gutter)
    maxw = pg.evaluate(
        "() => getComputedStyle(document.querySelector('.wrap')).maxWidth")
    ck("가로 확장", float(maxw.replace("px", "")) >= 1800, maxw)

    print("-- V6 시인성: 타이틀에 회색을 쓰지 않는다 --")
    # --muted 는 본문 보조 문구 전용. 영역 제목·표 머리글에는 쓰지 않는다.
    grey = pg.evaluate("""() => {
      const muted = getComputedStyle(document.documentElement)
        .getPropertyValue('--muted').trim();
      const bad = [];
      document.querySelectorAll('h1,h2,h2 small,th,.sec-t,.eyebrow,.crumb,.sumpane-h')
        .forEach(el => {
          if (getComputedStyle(el).color === muted) bad.push(el.className || el.tagName);
        });
      return bad.slice(0, 5);
    }""")
    ck("제목·머리글에 --muted 미사용", not grey, "; ".join(grey))

    print("-- V6 포트폴리오 범위 설명(57개인 이유) --")
    ck("범위 설명 블록", pg.locator(".scope-note").count() == 1)
    sn = pg.locator(".scope-note").inner_text()
    ck("'전량이 아님' 명시", "전량이 아닌" in sn, sn[:46].replace("\n", " "))
    for k in ("선정 기준", "제외 대상", "집계 단위"):
        ck(f"{k} 제시", k in sn)
    # 수치는 재수집 때마다 바뀐다. 값이 아니라 '제시하고 있는지'를 본다.
    import re as _re2
    ck("기술당 자사 특허 규모 제시",
       bool(_re2.search(r"평균\s*[\d,]+여?\s*건", sn)),
       (_re2.search(r"평균[^.]{0,20}", sn) or [""])[0])

    print("-- V6 총계 정합: 상단 KPI 가 전량을 센다 --")
    ksum = " ".join(pg.locator(".kpi-sum").inner_text().split())
    ck("합계 줄 존재", bool(ksum), ksum[:70])
    ck("합계 불일치 표시 없음", "불일치" not in ksum, ksum[:70])
    kn = pg.evaluate("""() => {
      const v=[...document.querySelectorAll('.kpi .v')].map(e=>+e.textContent);
      return {tiles:v.length, five:v.slice(0,5).reduce((a,b)=>a+b,0)};
    }""")
    ck("KPI 타일 6개(수준 5 + 경쟁사)", kn["tiles"] == 6, str(kn["tiles"]))
    ck("수준 5개 합 = 카드 수", kn["five"] == n_all, f"{kn['five']} / {n_all}")
    ck("부제 기술 수도 데이터 기준",
       pg.evaluate("()=>+document.querySelector('#deckN').textContent") == n_all)
    # 문장 안에 넣은 숫자 span 이 블록이 되면 '배터리 공정기술 / 73 / 개 전량'으로 끊긴다.
    ck("부제 숫자는 문장 안에 인라인",
       pg.evaluate("()=>getComputedStyle(document.querySelector('#deckN')).display")
       == "inline")
    dl = pg.evaluate("""() => {
      const el=[...document.querySelectorAll('.deck > span')];
      const lh=parseFloat(getComputedStyle(el[0]).lineHeight);
      return el.map(e=>Math.round(e.clientHeight/lh));
    }""")
    ck("부제 각 문장 한 줄(1200px 이상)", all(x == 1 for x in dl), str(dl))

    print("-- V6 최우선 검토 기술 필터: 다섯 구분 전량 조회 가능 --")
    want = {"behind": "열위 기술", "even": "동등 기술", "ahead": "우위 기술",
            "hold": "확인 필요", "none": "근거 부족"}
    fsum = 0
    for key, cls_name in want.items():
        btn = pg.locator(f'[data-f="{key}"]')
        if not btn.count():
            ck(f"'{cls_name}' 필터 존재", False, "버튼 없음")
            continue
        btn.click()
        pg.wait_for_timeout(320)
        rows = pg.locator("#tbody tr").count()
        kinds = pg.evaluate(
            "() => [...new Set([...document.querySelectorAll('#tbody .tcell')]"
            ".map(e => e.textContent.trim()))]")
        fsum += rows
        ck(f"'{cls_name}' 필터가 해당 구분만 표시", kinds == [cls_name],
           f"{rows}행 {kinds}")
    pg.locator('[data-f="all"]').click()
    pg.wait_for_timeout(320)
    allrows = pg.locator("#tbody tr").count()
    ck("다섯 필터 합 = 전체 = 카드 수", fsum == allrows == n_all,
       f"필터합 {fsum} / 전체 {allrows} / 카드 {n_all}")
    ck("필터 버튼 한 줄", pg.evaluate(
        """() => new Set([...document.querySelectorAll('#statusSeg button')]
             .map(b => Math.round(b.getBoundingClientRect().top))).size""") == 1)
    pg.locator('[data-f="behind"]').click()
    pg.wait_for_timeout(300)

    print("-- V6 '확인 필요' vs '근거 부족' — 뜻과 형태가 갈린다 --")
    ck("확인 필요 = 경쟁사 있음 · 자사 미확인",
       "경쟁사 근거 확보 · 자사 보유 현황 미확인" in body)
    ck("근거 부족 = 자사 확인 · 경쟁사 없음",
       "자사 현황 확인 · 경쟁사 근거 미확보" in body)
    shape = pg.evaluate("""() => {
      const h=document.querySelector('.pc.lv-hold'), n=document.querySelector('.pc.lv-none');
      if(!h||!n) return null;
      const H=getComputedStyle(h), N=getComputedStyle(n);
      const hb=getComputedStyle(h.querySelector('.pc-lv')),
            nb=getComputedStyle(n.querySelector('.pc-lv'));
      return {hBg:H.backgroundColor, nBg:N.backgroundColor,
              nDashed:N.borderTopStyle, hBadge:hb.backgroundColor, nBadge:nb.backgroundColor};
    }""")
    ck("두 카드 배경이 다르다", shape and shape["hBg"] != shape["nBg"],
       f"{shape['hBg']} vs {shape['nBg']}" if shape else "")
    ck("근거 부족은 점선 테두리", shape and shape["nDashed"] == "dashed",
       shape["nDashed"] if shape else "")
    ck("확인 필요 배지는 채움 · 근거 부족은 속 빈 배지",
       shape and shape["hBadge"] != shape["nBadge"]
       and "0, 0, 0, 0" in shape["nBadge"],
       f"{shape['hBadge']} vs {shape['nBadge']}" if shape else "")

    print("-- V6 조사 요약 · 근거 신뢰도 · 대응 기준선 --")
    ps = pg.locator("#posList").inner_text()
    ck("조사 요약이 목록이 아닌 요약", pg.locator("#posList .lvrow").count() >= 3,
       f"{pg.locator('#posList .lvrow').count()}행")
    ck("수준 분포 막대", pg.locator("#posList .lvbar i").count() >= 3)
    ck("요약 결론 문장", "최우선 보완 대상" in ps)
    ck("'근거 강도별 분포' 문구 제거", "근거 강도별" not in body)
    ck("'근거 신뢰도' 사용", "근거 신뢰도" in body)
    ck("'계보' 문구 제거", "계보" not in body)
    ck("판정 기준 등급 배너", pg.locator(".tgb").count() >= 1)
    ck("확인 주체 = 생산기술혁신센터",
       "생산기술혁신센터" in body and "공정기술팀" not in body)
    ck("격차 강조색이 마젠타가 아님", pg.evaluate(
        """() => {const e=document.querySelector('.pc-lag');
                 return !e || getComputedStyle(e).color !== 'rgb(229, 0, 125)';}"""))

    print("-- V6 3축 격차 모델 --")
    gapbtn = pg.locator("[data-lag]").first
    if gapbtn.count():
        gapbtn.click()
        pg.wait_for_timeout(500)
        m = pg.locator(".modal").inner_text()
        ck("듀얼 트랙 표기", "기준 시나리오" in m and "보수 시나리오" in m)
        ck("3축 표", pg.locator(".axt").count() == 1)
        ck("R&D 선행 격차 행", "R&D 선행 격차" in m)
        ck("양산 진입 격차 행", "양산 진입 격차" in m)
        ck("스펙 수준 격차 행", "스펙 수준 격차" in m)
        ck("미산출 축을 숨기지 않는다", "미산출" in m, "")
        ck("수율·원가 한계 명시", "수율" in m and "비공개" in m)
        ck("신뢰도 배지", pg.locator(".modal .cfb").count() >= 1)
        ck("실행 소요기간 분해 유지", "실행 소요기간" in m)
        ck("보정 계수 명시", "보정 계수" in m)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(250)
        pg.locator("[data-urg]").first.click(); pg.wait_for_timeout(500)
        um = pg.locator(".modal").inner_text()
        ck("시급도 대응 기준선 제시", "대응 기준선" in um)
        for lab in ("즉시 착수", "계획 반영", "검토 착수", "관찰"):
            ck(f"기준선 '{lab}'", lab in um)
        ck("기준선 근거(27·64·125) 명시",
           "27" in um and "64" in um and "125" in um)
        ck("현재 위치 표기", "◀ 현재" in um)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(250)
    else:
        ck("격차 팝업 진입", False, "data-lag 버튼 없음")

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
