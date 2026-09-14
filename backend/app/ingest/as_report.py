"""
as_report: AS 접수처리대장 (D테크 / M테크 / K테크 / 부산지사)
파일 1개 = 팀 × 장비군 × 월. 시트 '접수처리대장'(또는 '접수확인서') 에 케이스 1건/행.

레이아웃:
  row0..2  제목 영역, row 안에 "AS접수처리대장(<팀>) : <월>" / "... (2026년 N월)"
  헤더행   'NO' 셀이 있는 행 + 그 아래 부제 헤더행(출하처, 출하#(출하일), ...)
  data     NO 가 숫자인 행들

팀/장비군/월 판별:
  org      제목의 팀명(K테크솔루션팀/덴탈테크솔루션/부산팀) → 없으면 파일명("부산지사"/"덴탈"/"해외 AS보고서")
  line     파일명의 장비군 토큰 (C-ARM/DENTAL/DENTAL STANDARD/MAMMO/대장비/소장비)
  month    파일명 또는 제목의 'N월'

수리비용 열이 D/M/K 는 [통화기호 | 금액] 2칸, 부산은 [원화금액] 1칸이라
헤더맵 + 통화기호 감지로 이후 열을 +1 시프트해서 읽는다.
"""
from __future__ import annotations

import re

from .schema import ParsedReport, PeriodKey
from .xlsx_util import as_date, clean, find_anchor, grid, load, num

_CUR = {"$": "USD", "€": "EUR", "￥": "JPY", "¥": "JPY", "CNY": "CNY", "₩": "KRW", "\\": "KRW"}

# 부산 출하처 앞머리 도시 → 시·도
_BUSAN_CITY = {
    "대구": "대구", "울산": "울산", "경주": "경북", "포항": "경북", "구미": "경북",
    "창원": "경남", "김해": "경남", "양산": "경남", "진주": "경남", "거제": "경남",
    "밀양": "경남", "통영": "경남", "부산": "부산",
}
_KR_ANALYSIS_SHEET = ["월간 분석", "월간분석", "분석표"]
_MONTH = re.compile(r"(\d{1,2})\s*월")
_YEAR = re.compile(r"(20\d{2})\s*년|(\d{2})년")

_ORG_FROM_TITLE = [
    ("K테크솔루션", "K"), ("덴탈테크솔루션", "D"), ("부산", "부산"),
    ("M테크솔루션", "M"), ("메디칼", "M"),
]
_LINE_TOKENS = ["DENTAL STANDARD", "C-ARM", "C-Arm", "CARM", "DENTAL", "MAMMO", "대장비", "소장비"]

_SHEET_CANDIDATES = ["접수처리대장", "해외AS접수처리대장", "해외 AS접수처리대장",
                     "AS접수처리대장", "접수확인서"]


def _detect_org(title_text: str, filename: str) -> str:
    for key, org in _ORG_FROM_TITLE:
        if key in title_text:
            return org
    if "부산지사" in filename or "부산팀" in filename:
        return "부산"
    if filename.startswith("덴탈") or "덴탈 대장비" in filename or "덴탈 소장비" in filename:
        return "D"
    if filename.startswith("해외 AS보고서") or "해외 AS" in filename:
        return "M"
    return "K"  # K 파일은 팀 표기가 없음 (기본값)


def _detect_line(filename: str) -> str | None:
    up = filename.upper()
    for tok in _LINE_TOKENS:
        if tok.upper() in up:
            return {"CARM": "C-ARM", "C-ARM": "C-ARM"}.get(tok.upper(), tok.upper())
    return None


def parse_as_report(raw: bytes, filename: str) -> ParsedReport:
    rep = ParsedReport("as_report", PeriodKey("as_ledger", 2026))
    wb = load(raw)

    ws = None
    for cand in _SHEET_CANDIDATES:
        for n in wb.sheetnames:
            if cand in n.strip().replace(" ", ""):
                ws = wb[n]
                break
        if ws:
            break
    if ws is None:
        # 'Trouble shooting flow' 등 참조시트 제외하고 첫 시트
        for w in wb.worksheets:
            if "trouble" not in w.title.lower():
                ws = w
                break
        ws = ws or wb.worksheets[0]
        rep.warn(f"접수처리대장 시트 매칭 실패 → '{ws.title}' 사용")

    g = grid(ws)

    title_text = " ".join(str(c) for row in g[:4] for c in row if c)
    org = _detect_org(title_text, filename)
    line = _detect_line(filename)
    rep.scope_key = f"as:{org}:{line or '기타'}"

    ym = _MONTH.search(filename) or _MONTH.search(title_text)
    yy = _YEAR.search(filename) or _YEAR.search(title_text)
    year = 2026
    if yy:
        year = int(yy.group(1)) if yy.group(1) else 2000 + int(yy.group(2))
    month = int(ym.group(1)) if ym else None
    if not month:
        rep.warn(f"월 파싱 실패: {filename}")
    rep.period = PeriodKey("as_ledger", year, month, None,
                           label=f"{year}년 {month:02d}월 AS" if month else f"{filename}")

    # 헤더행 찾기: '출하처' 와 '조치사항' 이 같은 행에 있는 행
    hdr_row = None
    for r, row in enumerate(g[:12]):
        cells = [clean(c) for c in row]
        if "출하처" in cells and ("조치사항" in cells or "조치 후 점검" in cells):
            hdr_row = r
            break
    if hdr_row is None:
        rep.warn("헤더행(출하처/조치사항) 못 찾음 — 적재 중단")
        return rep

    hdr = [clean(c) or "" for c in g[hdr_row]]

    def col(*names, occurrence=0):
        found = [i for i, h in enumerate(hdr)
                 if any(h == nm or h.replace(" ", "") == nm.replace(" ", "") for nm in names)]
        return found[occurrence] if len(found) > occurrence else None

    ix = {
        "shipped_to": col("출하처"),
        "install_date": col("출하#(출하일)", "출하#", "출하일"),
        "product_model": col("제품명"),
        "serial_no": col("제조번호"),
        "udi": col("UDI"),
        "warranty": col("보증기간"),
        "ticket_no": col("접수번호"),
        "category": col("구분", occurrence=0),
        "received_date": col("접수일"),
        "action_date": col("처리일"),
        "engineer": col("조치자"),
        "symptom": col("접수내용"),
        "action": col("조치사항"),
        "check_result": col("조치후점검", "조치 후 점검"),
        "result": col("결과"),
        "repair": col("수리비용"),
        "billing": col("청구내역"),
        "cause": col("원인분석"),
        "fix_class": col("구분", occurrence=1) or col("구분", occurrence=-0),  # 두 번째 '구분'
        "adverse_event": col("이상사례"),
        "followup": col("후속조치"),
    }
    # '구분' 두 개(접수구분 / 시정조치구분). 헤더가 열 구조를 이미 반영하므로 시프트 불필요.
    dupe = [i for i, h in enumerate(hdr) if h == "구분"]
    if len(dupe) >= 2:
        ix["category"], ix["fix_class"] = dupe[0], dupe[1]
    elif ix["cause"] is not None:
        ix["fix_class"] = ix["cause"] + 1  # 원인분석 바로 다음 칸

    count = 0
    rows: list[dict] = []
    for row in g[hdr_row + 1:]:
        no = num(row[0]) if row else None
        model = clean(row[ix["product_model"]]) if ix["product_model"] is not None and ix["product_model"] < len(row) else None
        if no is None and not model:
            continue
        if clean(row[0]) in ("합계", "소계", "계"):
            break

        rc = ix["repair"]
        repair_cur = repair_amt = None
        if rc is not None and rc < len(row):
            sym = clean(row[rc])
            if sym in _CUR:                       # [통화기호 | 금액] 2칸 구조 (D/M/K)
                repair_cur = _CUR[sym]
                repair_amt = num(row[rc + 1]) if rc + 1 < len(row) else None
            else:                                # [원화금액] 1칸 구조 (부산 등)
                repair_amt = num(row[rc])
                repair_cur = "KRW" if repair_amt else None

        def gv(key, conv=clean):
            i = ix[key]
            if i is None or i >= len(row):
                return None
            return conv(row[i])

        shipped = gv("shipped_to")
        overseas = org in ("D", "M")
        region_kr = None
        if not overseas and shipped:
            if org == "부산":
                head = shipped.split(",")[0].split(" ")[0].strip()
                region_kr = next((v for k, v in _BUSAN_CITY.items() if head.startswith(k)), "부산")
            # K 는 아래 _merge_kr_analysis 에서 채움
        rows.append(dict(
            org=org, product_line=line, seq_no=int(no) if no is not None else None,
            ticket_no=gv("ticket_no"), shipped_to=shipped,
            is_overseas=overseas,
            country=shipped if overseas else None,
            region_kr=region_kr,
            install_date=gv("install_date", as_date),
            product_model=model, serial_no=gv("serial_no"), udi=gv("udi"),
            warranty=gv("warranty"), category=gv("category"),
            received_date=gv("received_date", as_date),
            action_date=gv("action_date", as_date),
            engineer=gv("engineer"), symptom=gv("symptom"), action=gv("action"),
            check_result=gv("check_result"), result=gv("result") or "완료",
            repair_currency=repair_cur, repair_amount=repair_amt,
            billing=gv("billing"), cause=gv("cause"),
            fix_class=gv("fix_class"), adverse_event=gv("adverse_event"),
            followup=gv("followup"),
        ))
        count += 1

    if org == "K":
        _merge_kr_analysis(wb, rows, rep)

    for r in rows:
        rep.add("as_ticket", **r)
    if count == 0:
        rep.warn("데이터행 0건")
    return rep


def _merge_kr_analysis(wb, rows: list[dict], rep: ParsedReport) -> None:
    """K테크 '월간 분석' 시트에서 지역·고장코드·사용연한을 seq_no 로 매칭 병합."""
    ws = None
    for cand in _KR_ANALYSIS_SHEET:
        for n in wb.sheetnames:
            if cand in n.replace(" ", ""):
                ws = wb[n]
                break
        if ws:
            break
    if ws is None:
        return
    g = grid(ws)
    hr = None
    for r, row in enumerate(g[:15]):
        cells = [clean(c) for c in row]
        if "병원명" in cells and "지역" in cells:
            hr = r
            break
    if hr is None:
        return
    hdr = [clean(c) or "" for c in g[hr]]
    sub = [clean(c) or "" for c in g[hr + 1]] if hr + 1 < len(g) else []

    def ci(*names, hdr_row=hdr):
        for nm in names:
            for i, h in enumerate(hdr_row):
                if h == nm:
                    return i
        return None

    c_no = ci("NO", "No")
    c_reg = ci("지역")
    c_major = ci("중분류", hdr_row=sub)
    c_minor = ci("소분류", hdr_row=sub)
    c_act = ci("조치분류", hdr_row=sub)
    c_age = ci("기간별")
    if c_age is not None:  # '기간별' 헤더 밑 실제 값은 병합으로 같은 열
        pass
    by_seq: dict[int, dict] = {}
    for row in g[hr + 2:]:
        n = num(row[c_no]) if c_no is not None and c_no < len(row) else None
        if n is None:
            continue
        by_seq[int(n)] = {
            "region_kr": clean(row[c_reg]) if c_reg is not None and c_reg < len(row) else None,
            "cause_major": clean(row[c_major]) if c_major is not None and c_major < len(row) else None,
            "cause_minor": clean(row[c_minor]) if c_minor is not None and c_minor < len(row) else None,
            "action_class": clean(row[c_act]) if c_act is not None and c_act < len(row) else None,
            "age_bucket": clean(row[c_age]) if c_age is not None and c_age < len(row) else None,
        }
    hit = 0
    for r in rows:
        m = by_seq.get(r.get("seq_no"))
        if m:
            for k, v in m.items():
                if v:
                    r[k] = v
            hit += 1
    if hit == 0:
        rep.warn("월간 분석 시트 매칭 0건 (seq_no 불일치)")
