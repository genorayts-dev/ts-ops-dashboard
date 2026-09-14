"""
gsheet_master: 통합 구글 시트 (탭 5개) → as_ticket + receivable

탭 구성:
  'AS 매출 K테크'      : No.|접수일|조치일|지역|제품분류|제품명(사양)|제조번호/코드|보증구분|
                          담당자|증상/내용|조치사항|불량구분|통화|수리비용|결과
  'AS 매출 해외'       : No.|팀|발송일|지역|국가/거래처|제품명(사양)|제조번호/코드|보증구분|
                          담당자|증상/내용|(빈)|통화|수리비용|결과
  'AS MD 서비스 건수'  : No.|팀|유형|접수일|조치일|지역|국가/거래처|제품명(사양)|제조번호/코드|
                          보증구분|담당자|증상/내용|조치사항|불량구분|제품분류|결과
  'AS 채권 D' / 'AS 채권 M':
                          No.|팀|채널구분|법인/거래처|국가|통화|청구금액|입금액|잔액|
                          발송일|입금예정일|연체여부|비고

하나의 batch 로 적재. scope_key='gsheet_master' → 재동기화 시 이전 batch 대체.
"""
from __future__ import annotations

import re

from .schema import ParsedReport, PeriodKey
from .xlsx_util import as_date, clean, grid, load, num

_CUR = {"$": "USD", "USD": "USD", "€": "EUR", "EUR": "EUR", "￥": "JPY", "¥": "JPY",
        "JPY": "JPY", "CNY": "CNY", "₩": "KRW", "KRW": "KRW", "\\": "KRW"}
_TEAM = {"D테크": "D", "D테크솔루션": "D", "M테크": "M", "M테크솔루션": "M",
         "K테크": "K", "K테크솔루션": "K"}
_KR_REGION = {  # 시·군 → 시·도  (지도용, 자주 나오는 것만; 없으면 원문 유지)
    "일산": "경기", "논산": "충청", "세종": "세종", "안양": "경기", "고양": "경기",
    "용인": "경기", "동작": "서울", "강남": "서울", "대전": "대전", "평택": "경기",
    "동대문": "서울", "과천": "경기", "수원": "경기", "성남": "경기", "부천": "경기",
    "인천": "인천", "부산": "부산", "대구": "대구", "울산": "울산", "광주": "광주",
    "청주": "충청", "천안": "충청", "전주": "전라", "창원": "경남", "김해": "경남",
    "포항": "경북", "구미": "경북", "강릉": "강원", "원주": "강원", "춘천": "강원",
    "제주": "제주",
}
_COUNTRY_IN_PAREN = re.compile(r"\(([^()]+)\)\s*$")


def _tab(wb, *needles):
    for n in wb.sheetnames:
        if n.startswith("_"):  # 자동화 스크립트가 만드는 내부 스테이징 탭(_D_K_AS 등)은 제외
            continue
        s = n.replace(" ", "")
        if all(x.replace(" ", "") in s for x in needles):
            return n
    return None


def _tab_any(wb, *needle_groups):
    """needle_groups = 여러 (needle, needle, ...) 튜플. 각 그룹은 AND, 그룹끼리는 OR.
    탭 이름 규칙이 바뀌어도(예: 'AS 매출 K테크' → 'K AS매출') 옛/새 이름을 모두 인식."""
    for group in needle_groups:
        t = _tab(wb, *group)
        if t:
            return t
    return None


def detect(wb) -> bool:
    names = [n.replace(" ", "") for n in wb.sheetnames]
    old_hits = sum(any(k in n for n in names)
                   for k in ("AS매출K", "AS매출해외", "AS발송해외", "AS채권", "MD서비스", "MD방문"))
    new_hits = sum(any(k in n for n in names) for k in ("AS매출", "채권", "유지보수", "MDAS"))
    return old_hits >= 2 or new_hits >= 3


def _header_row(g):
    for r, row in enumerate(g[:6]):
        cells = [clean(c) for c in row]
        if "No." in cells or "No" in cells or "번호" in cells:
            return r
    return 1


def _colmap(g, hr):
    hdr = [clean(c) or "" for c in g[hr]]
    return {h: i for i, h in enumerate(hdr) if h}


def _get(row, idx, conv=clean):
    return conv(row[idx]) if idx is not None and idx < len(row) and row[idx] is not None else None


def _col(c: dict, *names):
    """헤더명 후보 중 첫 매칭 열 인덱스 (탭마다 컬럼명이 달라 별칭 허용)."""
    for n in names:
        if n in c:
            return c[n]
    return None


def _split_site_serial(text: str | None):
    """'논산 논산속편한내과의원 GMA-707005-50726' → (site, serial).
       마지막 공백 뒤 토큰이 시리얼 패턴이면 분리."""
    if not text:
        return None, None
    t = text.strip().strip("()")
    m = re.search(r"([A-Z0-9]{4,}[-A-Z0-9]*)\s*$", t)
    if m and any(ch.isdigit() for ch in m.group(1)):
        return t[: m.start()].strip(" -") or None, m.group(1)
    return t, None


def parse_gsheet_master(raw: bytes, filename: str) -> ParsedReport:
    rep = ParsedReport("gsheet_master",
                       PeriodKey("consolidated", 2026, label="AS 마스터 (구글시트)"))
    rep.scope_key = "gsheet_master"
    wb = load(raw)

    _parse_k(wb, rep)
    _parse_overseas(wb, rep)
    _parse_md(wb, rep)
    for tab, team in ((_tab_any(wb, ("AS채권D",), ("D", "채권")), "D"),
                      (_tab_any(wb, ("AS채권M",), ("M", "채권")), "M"),
                      (_tab_any(wb, ("AS채권K",), ("K", "채권")), "K")):
        if tab:
            _parse_receivable(grid(wb[tab]), team, rep)
        elif team != "K":  # K(국내) 탭은 아직 없을 수 있음
            rep.warn(f"채권 {team} 탭 없음")
    _parse_maintenance(wb, rep)
    return rep


def _parse_maintenance(wb, rep):
    """'AS 유지보수 K' 탭 → maintenance_contract (K테크 유지보수 월납 계약).
       컬럼: 순번|병원명|장비|S/N|장비 납품일|유지보수 계약일|계약 만료일|입금일|유지보수 금액(월납)
    """
    tab = _tab_any(wb, ("AS유지보수",), ("유지보수계약",), ("유지보수",))
    if not tab:
        rep.warn("'AS 유지보수 K' 탭 없음 — K 유지보수 매출 미반영")
        return
    g = grid(wb[tab])
    hr = 0
    for r, row in enumerate(g[:8]):
        cells = [clean(x) or "" for x in row]
        if any("병원" in x or "거래처" in x for x in cells) and any("금액" in x or "월납" in x for x in cells):
            hr = r
            break
    c = _colmap(g, hr)
    i_hosp = _col(c, "병원명", "거래처", "고객명")
    i_dev = _col(c, "장비", "장비명", "제품명", "제품명(사양)", "모델")
    i_sn = _col(c, "S/N", "SN", "제조번호", "제조번호/코드", "시리얼")
    i_deliv = _col(c, "장비 납품일", "납품일", "설치일", "출하일")
    i_start = _col(c, "유지보수 계약일", "계약일", "계약 시작일", "시작일")
    i_end = _col(c, "계약 만료일", "만료일", "종료일")
    i_pay = _col(c, "입금일", "결제일", "청구일")
    i_fee = _col(c, "유지보수 금액(월납)", "유지보수 금액", "월납액", "월 금액", "금액")
    i_cur = _col(c, "통화")
    n = 0
    for row in g[hr + 1:]:
        hosp = _get(row, i_hosp)
        fee = _get(row, i_fee, num)
        if not hosp or not fee:
            continue
        end_raw = (_get(row, i_end) or "").strip()
        expires = None if end_raw in ("", "-", "–", "—", "무기한", "없음") \
            else _get(row, i_end, as_date)
        cur = _CUR.get((_get(row, i_cur) or "").strip()) or "KRW"  # 통화 미기재 = KRW
        rep.add("maintenance_contract", team_code="K",
                hospital=hosp,
                device=_get(row, i_dev),
                serial_no=_get(row, i_sn),
                delivered_on=_get(row, i_deliv, as_date),
                contract_on=_get(row, i_start, as_date),
                expires_on=expires,
                pay_day=_get(row, i_pay),
                currency=cur,
                monthly_fee=int(round(fee)),
                active=True,
                note=None)
        n += 1
    if not n:
        rep.warn("유지보수 계약 데이터 0건")


def _parse_k(wb, rep):
    tab = _tab_any(wb, ("AS매출K",), ("K", "AS매출"))
    if not tab:
        rep.warn("'AS 매출 K테크' 탭 없음")
        return
    g = grid(wb[tab])
    hr = _header_row(g)
    c = _colmap(g, hr)
    n = 0
    for row in g[hr + 1:]:
        no = num(row[c.get("No.", 0)]) if row else None
        model = _get(row, c.get("제품명(사양)"))
        if no is None and not model:
            continue
        site, serial = _split_site_serial(_get(row, c.get("제조번호/코드")))
        reg = _get(row, c.get("지역"))
        cur = _CUR.get((_get(row, c.get("통화")) or "").strip())
        amt = num(row[c["수리비용"]]) if "수리비용" in c and c["수리비용"] < len(row) else None
        rep.add("as_ticket", org="K", is_overseas=False, src="k_dom",
                seq_no=int(no) if no is not None else None,
                region_kr=_KR_REGION.get(reg, reg), region=reg,
                shipped_to=site, serial_no=serial,
                product_model=model, product_line=_get(row, c.get("제품분류")),
                warranty=_get(row, c.get("보증구분")),
                received_date=_get(row, c.get("접수일"), as_date),
                action_date=_get(row, c.get("조치일"), as_date),
                engineer=_get(row, c.get("담당자")),
                symptom=_get(row, c.get("증상/내용")),
                action=_get(row, c.get("조치사항")),
                fix_class=_get(row, c.get("불량구분")),
                repair_currency=cur or ("KRW" if amt else None), repair_amount=amt,
                result=_get(row, c.get("결과")) or "완료")
        n += 1
    if not n:
        rep.warn("K테크 매출 데이터 0건")


def _parse_overseas(wb, rep):
    tab = _tab_any(wb, ("AS매출해외",), ("AS발송해외",), ("MD", "매출"))
    if not tab:
        rep.warn("'AS 매출 해외' 탭 없음")
        return
    g = grid(wb[tab])
    hr = _header_row(g)
    c = _colmap(g, hr)
    n = 0
    for row in g[hr + 1:]:
        no = num(row[c.get("No.", 0)]) if row else None
        model = _get(row, c.get("제품명(사양)"))
        if no is None and not model:
            continue
        gc = _get(row, c.get("국가/거래처")) or ""
        m = _COUNTRY_IN_PAREN.search(gc)
        country = m.group(1).strip() if m else None
        dealer = _COUNTRY_IN_PAREN.sub("", gc).strip() or None
        cur = _CUR.get((_get(row, c.get("통화")) or "").strip())
        amt = num(row[c["수리비용"]]) if "수리비용" in c and c["수리비용"] < len(row) else None
        rep.add("as_ticket", org=_TEAM.get(_get(row, c.get("팀")) or "", "M"),
                is_overseas=True, src="overseas_ship",
                seq_no=int(no) if no is not None else None,
                country=country, shipped_to=dealer, region=_get(row, c.get("지역")),
                product_model=model, serial_no=_get(row, c.get("제조번호/코드")),
                warranty=_get(row, c.get("보증구분")),
                action_date=_get(row, c.get("발송일"), as_date),
                received_date=_get(row, c.get("발송일"), as_date),
                engineer=_get(row, c.get("담당자")),
                symptom=_get(row, c.get("증상/내용")),
                repair_currency=cur, repair_amount=amt,
                result=_get(row, c.get("결과")) or "완료")
        n += 1
    if not n:
        rep.warn("해외 매출 데이터 0건")


def _parse_md(wb, rep):
    tab = _tab_any(wb, ("MD서비스",), ("MD방문",), ("MD서비스건수",), ("MD", "AS"))
    if not tab:
        rep.warn("'AS MD 서비스' 탭 없음")
        return
    g = grid(wb[tab])
    hr = _header_row(g)
    c = _colmap(g, hr)
    n = 0
    for row in g[hr + 1:]:
        no = num(row[c.get("No.", 0)]) if row else None
        model = _get(row, c.get("제품명(사양)"))
        if no is None and not model:
            continue
        gc = _get(row, c.get("국가/거래처")) or ""
        m = _COUNTRY_IN_PAREN.search(gc)
        country = (m.group(1).strip() if m else gc.strip()) or None
        overseas = bool(country) and country not in _KR_REGION and not _KR_REGION.get(country)
        cur = _CUR.get((_get(row, c.get("통화")) or "").strip())
        amt = num(row[c["수리비용"]]) if "수리비용" in c and c["수리비용"] < len(row) else None
        rep.add("as_ticket", org=_TEAM.get(_get(row, c.get("팀")) or "", "M"),
                is_overseas=overseas, src="md_service",
                seq_no=int(no) if no is not None else None,
                category=_get(row, c.get("유형")),
                country=country if overseas else None,
                region_kr=(None if overseas else _KR_REGION.get(country, country)),
                region=_get(row, c.get("지역")),
                product_model=model, product_line=_get(row, c.get("제품분류")),
                serial_no=_get(row, c.get("제조번호/코드")),
                warranty=_get(row, c.get("보증구분")),
                received_date=_get(row, c.get("접수일"), as_date),
                action_date=_get(row, c.get("조치일"), as_date),
                engineer=_get(row, c.get("담당자")),
                symptom=_get(row, c.get("증상/내용")),
                action=_get(row, c.get("조치사항")),
                fix_class=_get(row, c.get("불량구분")),
                repair_currency=cur, repair_amount=amt,
                result=_get(row, c.get("결과")) or "완료")
        n += 1
    if not n:
        rep.warn("MD 서비스 데이터 0건")


def _parse_receivable(g, team, rep):
    hr = _header_row(g)
    c = _colmap(g, hr)
    # 탭마다 컬럼명이 조금씩 다름 (D/M: 법인/거래처·채널구분·발송일·입금예정일·통화 / K국내: 거래처·장비명·발생일·회수일자, 통화·국가 없음)
    i_no = _col(c, "No.", "No", "번호") or 0
    i_ent = _col(c, "법인/거래처", "거래처", "법인", "병원")
    i_chan = _col(c, "채널구분", "채널", "장비구분", "장비명", "구분")
    i_cur = _col(c, "통화")
    i_ctry = _col(c, "국가")
    i_amt = _col(c, "청구금액", "미회수금액", "매출금액")
    i_paid = _col(c, "입금액", "회수금액", "회수 금액")
    i_bal = _col(c, "잔액")
    i_ship = _col(c, "발송일", "발생일", "매출일자", "매출 일자")
    i_due = _col(c, "입금예정일", "회수일자", "회수 일자", "회수일")
    i_st = _col(c, "연체여부", "상태")
    i_note = _col(c, "비고", "처리내역")
    n = 0
    for row in g[hr + 1:]:
        no = num(row[i_no]) if row and i_no is not None and i_no < len(row) else None
        entity = _get(row, i_ent)
        if no is None and not entity:
            continue
        cur = _CUR.get((_get(row, i_cur) or "").strip())
        if not cur and team == "K":     # 국내(K) 탭은 통화 미기재 = KRW
            cur = "KRW"
        st = (_get(row, i_st) or "").strip()
        rep.add("receivable", team_code=team,
                party_type=_get(row, i_chan),
                entity=entity,
                country=_get(row, i_ctry) or ("한국" if team == "K" else None),
                currency=cur,
                amount=_get(row, i_amt, num), paid_amount=_get(row, i_paid, num),
                balance=_get(row, i_bal, num),
                ship_date=_get(row, i_ship, as_date),
                due_date=_get(row, i_due, as_date),
                is_new=st in ("연체", "미회수", "장기미수"),
                status=st or None,
                note=_get(row, i_note))
        n += 1
    if not n:
        rep.warn(f"채권 {team} 데이터 0건")
