"""
weekly_new: TS본부_주간업무(YYYY년 N월 N주).xlsx  (5월 4주 이후 표준)
시트: '0. 주간보고(TS본부)', '1. D테크', '2. M테크', '3. K테크'

주의: 팀 상세 시트는 A열(index 0)이 비어 있고 내용이 B열(index 1)부터 시작한다.
      그래서 모든 표는 '앵커 셀의 열'을 기준열(c0)로 삼아 상대 오프셋으로 읽는다.

'0. 주간보고(TS본부)' 요약표(헤더 '구분'):
    구분 | AS접수/완료 | · | Inbound | · | AS 매출 | · | AS 매출(26년 누계)
    D테크 / M테크 / K테크 / 합계

'1. D테크' / '2. M테크':
    1-1 상세 지역별   c0 | 총건수 | 완료 | 미완료 | 완료율 | GK건수 | 법인건수
    1-2 S/W & H/W 분류  c0=카테고리 | c0+1=세부 | c0+2.. 값
    2-1 수금현황       c0="국가\n(대리점)" | 통화 | 금액 | 장비명 | 입금일
    2-2 채권현황       c0=구분 | c0+1=법인코드 | c0+2=국가 | 통화/금액/… 스캔

'3. K테크':
    1 금주 AS현황 (방문/출하/Inbound/총대응)
    2 AS매출 (Medical/Dental/유지보수/센서보상 x 금주/누계)
    3-1/3-2/3-3 장비 모델별 방문
    5 장비별 출하
"""
from __future__ import annotations

import re

from .schema import ParsedReport, PeriodKey
from .xlsx_util import as_date, as_int, clean, find_anchor, grid, load, num

_TEAM_LABEL = {"D테크": "D", "M테크": "M", "K테크": "K"}
_REGIONS = ("아시아", "CIS", "중동", "아프리카", "중국", "오세아니아", "유럽", "남미", "북미")
_SKIP_MODELS = ("구분", "합계", "금주", "계", "총계", "차주")

_FILE_RE_PAREN = re.compile(r"\((?P<y>\d{4})\D{0,3}(?P<m>\d{1,2})\D{0,3}월\D{0,3}(?P<w>\d{1,2})\D{0,3}주")
_FILE_RE_LOOSE = re.compile(r"(?P<m>\d{1,2})\s*월\s*(?P<w>\d{1,2})\s*주")


def _period(filename: str, wb, rep: ParsedReport) -> PeriodKey:
    m = _FILE_RE_PAREN.search(filename) or _FILE_RE_LOOSE.search(filename)
    if m:
        y = int(m.groupdict().get("y") or 2026)
        return PeriodKey("weekly", y, int(m["m"]), int(m["w"]), label=f"{y}년 {int(m['m'])}월 {int(m['w'])}주")
    # 파일명 실패 → 요약 시트 상단 "■ TS본부 N월 N주차 주간보고"
    name = _match_sheet(wb, "0. 주간보고") or _match_sheet(wb, "주간보고")
    if name:
        for row in grid(wb[name])[:6]:
            for cell in row:
                mm = _FILE_RE_LOOSE.search(str(cell or "").replace("주차", "주"))
                if mm:
                    return PeriodKey("weekly", 2026, int(mm["m"]), int(mm["w"]),
                                     label=f"2026년 {int(mm['m'])}월 {int(mm['w'])}주")
    rep.warn(f"파일명에서 기간 파싱 실패: {filename}")
    return PeriodKey("weekly", 2026, None, None, label=filename)


def parse_weekly_new(raw: bytes, filename: str) -> ParsedReport:
    rep = ParsedReport("weekly_new", PeriodKey("weekly", 2026))
    wb = load(raw)
    rep.period = _period(filename, wb, rep)

    _parse_summary(wb, rep)
    for prefix, team in (("1. D테크", "D"), ("2. M테크", "M")):
        name = _match_sheet(wb, prefix)
        if name:
            _parse_dm_team(grid(wb[name]), team, rep)
        else:
            rep.warn(f"시트 없음: {prefix}")
    kname = _match_sheet(wb, "3. K테크")
    if kname:
        _parse_k_team(grid(wb[kname]), rep)
    else:
        rep.warn("시트 없음: 3. K테크")
    return rep


def _match_sheet(wb, prefix: str) -> str | None:
    for n in wb.sheetnames:
        if n.strip().startswith(prefix):
            return n
    return None


def _cell(row: list, i: int):
    return row[i] if 0 <= i < len(row) else None


# --------------------------------------------------------------------------
def _parse_summary(wb, rep: ParsedReport) -> None:
    name = _match_sheet(wb, "0. 주간보고") or _match_sheet(wb, "주간보고")
    if not name:
        rep.warn("요약 시트('0. 주간보고(TS본부)') 없음")
        return
    g = grid(wb[name])
    a = find_anchor(g, "구분")
    if not a:
        rep.warn("요약표 앵커 '구분' 없음")
        return
    r0, c0 = a
    for dr in range(1, 8):
        row = g[r0 + dr] if r0 + dr < len(g) else []
        label = clean(_cell(row, c0))
        team = _TEAM_LABEL.get(label or "")
        if not team:
            if label == "합계":
                break
            continue
        rep.add("svc_summary", team_code=team,
                received=as_int(_cell(row, c0 + 1)),
                inbound=as_int(_cell(row, c0 + 3)),
                revenue_krw=as_int(_cell(row, c0 + 5)),
                revenue_krw_ytd=as_int(_cell(row, c0 + 7)))


# --------------------------------------------------------------------------
def _parse_dm_team(g: list[list], team: str, rep: ParsedReport) -> None:
    _region_table(g, team, rep)
    _swhw_table(g, team, rep)
    _collection_table(g, team, rep)
    _receivable_table(g, team, rep)


def _region_table(g, team, rep):
    a = find_anchor(g, "상세 지역별")
    if not a:
        rep.warn(f"[{team}] '상세 지역별' 없음")
        return
    r0, c0 = a
    for dr in range(1, 14):
        row = g[r0 + dr] if r0 + dr < len(g) else []
        region = clean(_cell(row, c0))
        if not region:
            continue
        if region in ("합계", "총계"):
            break
        if region in _REGIONS:
            rep.add("svc_region", team_code=team, region=region,
                    total=as_int(_cell(row, c0 + 1)), completed=as_int(_cell(row, c0 + 2)),
                    incomplete=as_int(_cell(row, c0 + 3)), rate=num(_cell(row, c0 + 4)))


def _swhw_table(g, team, rep):
    a = find_anchor(g, "S/W & H/W 분류") or find_anchor(g, "S/W & H/W")
    if not a:
        rep.warn(f"[{team}] 'S/W & H/W 분류' 없음")
        return
    r0, c0 = a
    cat = None
    for dr in range(1, 45):
        row = g[r0 + dr] if r0 + dr < len(g) else []
        head = clean(_cell(row, c0))
        sub = clean(_cell(row, c0 + 1))
        val = None
        for k in range(2, 6):
            n = num(_cell(row, c0 + k))
            if n is not None:
                val = int(round(n))
                break
        if head in ("S/W", "H/W", "지원", "Inbound"):
            cat = {"S/W": "SW", "H/W": "HW", "지원": "지원", "Inbound": "Inbound"}[head]
        if head == "총계":
            break
        if cat and sub and sub != "계" and val is not None:
            rep.add("defect_breakdown", team_code=team, category=cat, subtype=sub, cnt_period=val)


def _collection_table(g, team, rep):
    a = find_anchor(g, "수금현황")
    if not a:
        return
    r0, c0 = a
    for dr in range(2, 30):
        row = g[r0 + dr] if r0 + dr < len(g) else []
        head = clean(_cell(row, c0))
        if not head or head in ("국가", "국가\n(대리점)"):
            continue
        if head == "합계":
            break
        country, dealer = head, None
        for sep in ("\n", "/"):
            if sep in head:
                country, dealer = head.split(sep, 1)
                country, dealer = country.strip(), dealer.strip(" ()")
                break
        cur = _cur(clean(_cell(row, c0 + 1)))
        amt = num(_cell(row, c0 + 2))
        if cur and amt is not None:
            rep.add("collection_line", team_code=team, country=country, dealer=dealer,
                    currency=cur, amount=amt, equipment=clean(_cell(row, c0 + 3)),
                    paid_date=as_date(_cell(row, c0 + 4)))


def _receivable_table(g, team, rep):
    a = find_anchor(g, "채권현황")
    if not a:
        return
    r0, c0 = a
    party = entity = None
    for dr in range(2, 130):
        row = g[r0 + dr] if r0 + dr < len(g) else []
        if not any(clean(x) for x in row):
            continue
        first = clean(_cell(row, c0))
        second = clean(_cell(row, c0 + 1))
        if first in ("법인", "GK"):
            party = first
        if first in ("GAI", "GEG", "GT", "GJ", "GS") or second in ("GAI", "GEG", "GT", "GJ", "GS"):
            entity = first if first in ("GAI", "GEG", "GT", "GJ", "GS") else second
        if (first or "").startswith("Total") or (second or "").startswith("Total"):
            continue
        if first and first.startswith("2-3"):
            break
        country = clean(_cell(row, c0 + 2))
        cur = None
        nums, dates = [], []
        for i, cell in enumerate(row):
            s = clean(cell)
            if s in ("$", "€", "￥", "¥", "CNY", "₩"):
                cur = _cur(s)
            n = num(cell)
            if n is not None and i > c0 + 2:
                nums.append(n)
            d = as_date(cell)
            if d:
                dates.append(d)
        if cur and nums:
            amt = nums[0]
            paid = nums[1] if len(nums) >= 2 else None
            bal = nums[2] if len(nums) >= 3 else (amt - (paid or 0))
            if amt:
                rep.add("receivable", team_code=team, party_type=party, entity=entity,
                        country=country, currency=cur, amount=amt, paid_amount=paid, balance=bal,
                        ship_date=dates[0] if dates else None,
                        due_date=dates[1] if len(dates) > 1 else None)


# --------------------------------------------------------------------------
def _parse_k_team(g: list[list], rep: ParsedReport) -> None:
    for anchor, group in (("3-1 C-arm", "C-arm"), ("3-2 Mammo", "Mammo"), ("3-3 Dental", "Dental")):
        a = find_anchor(g, anchor)
        if not a:
            rep.warn(f"[K] '{anchor}' 없음")
            continue
        r0, c0 = a
        hdr = g[r0 + 1] if r0 + 1 < len(g) else []
        vals = g[r0 + 2] if r0 + 2 < len(g) else []
        for i in range(c0 + 1, len(hdr)):
            m = clean(hdr[i])
            if not m or m in _SKIP_MODELS:
                continue
            rep.add("equipment_stat", team_code="K", product_group=group,
                    model=m, visit_cnt=as_int(_cell(vals, i)))

    a = find_anchor(g, "5. 장비별 출하 건수")
    if a:
        r0, c0 = a
        hdr = g[r0 + 1] if r0 + 1 < len(g) else []
        vals = g[r0 + 2] if r0 + 2 < len(g) else []
        for i in range(c0 + 1, len(hdr)):
            m = clean(hdr[i])
            if not m or m in _SKIP_MODELS:
                continue
            rep.add("equipment_stat", team_code="K", product_group=None,
                    model=m, shipment_cnt=as_int(_cell(vals, i)))

    a = find_anchor(g, "2. AS매출")
    if a:
        r0, c0 = a
        for dr in range(1, 6):
            row = g[r0 + dr] if r0 + dr < len(g) else []
            label = clean(_cell(row, c0))
            if label == "금주 AS 매출":
                rep.add("svc_summary", team_code="K", revenue_krw=as_int(row[-1]))
            elif label == "26년 누계":
                rep.add("svc_summary", team_code="K", revenue_krw_ytd=as_int(row[-1]))

    a = find_anchor(g, "금주 AS현황")
    if a:
        r0, c0 = a
        total = None
        for dr in range(1, 8):
            row = g[r0 + dr] if r0 + dr < len(g) else []
            if clean(_cell(row, c0)) == "합계":
                # 방문 AS완료 합계
                total = as_int(_cell(row, c0 + 2))
        if total is not None:
            rep.add("svc_summary", team_code="K", completed=total)


def _cur(sym: str | None) -> str | None:
    return {"$": "USD", "€": "EUR", "￥": "JPY", "¥": "JPY", "CNY": "CNY",
            "₩": "KRW", "\\": "KRW"}.get((sym or "").strip())
