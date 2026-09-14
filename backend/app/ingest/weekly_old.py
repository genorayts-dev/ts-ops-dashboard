"""
weekly_old: *주간회의록*.xlsx (1~5월 초 양식)

시트: '주간회의록(양식)', 'TS본부 주간업무보고', 'K/M/D테크솔루션',
      'K/M/D테크솔루션 서비스 이력', 'M·D테크솔루션 지원 AS현황', '환율', 백업용

요약표는 신양식과 사실상 동일:
  'TS본부 주간업무보고' 시트, 헤더 '구분' | AS접수/완료 | Inbound | AS매출 | 26년 누계
  행: K테크솔루션팀 / M테크솔루션팀 / D테크솔루션팀

기간은 파일명이 아니라 시트 A2 텍스트 "■ TS본부 N월 N주차 주간보고" 에서.

TODO(실파일 대조 후 확정):
  * 'K테크솔루션' 시트의 3-x 장비 모델 표 좌표 (신양식 K테크와 유사하나 열 위치 편차)
  * 'M·D테크솔루션 지원 AS현황' → svc_case 컬럼 매핑
  * '환율' 시트 → fx_plan upsert (사업계획 환율은 연 1회라 보통 스킵)
"""
from __future__ import annotations

import re

from .schema import ParsedReport, PeriodKey
from .weekly_new import _cur  # 재사용
from .xlsx_util import as_date, as_int, clean, find_anchor, grid, load, num

_TITLE_RE = re.compile(r"(?P<m>\d{1,2})\s*월\s*(?P<w>\d{1,2})\s*주차")
_TEAM_LABEL = {"K테크솔루션팀": "K", "M테크솔루션팀": "M", "D테크솔루션팀": "D"}


def parse_weekly_old(raw: bytes, filename: str) -> ParsedReport:
    rep = ParsedReport("weekly_old", PeriodKey("weekly", 2026))
    wb = load(raw)

    sname = _find(wb, "TS본부 주간업무보고")
    if not sname:
        rep.warn("'TS본부 주간업무보고' 시트 없음 — 파싱 불가")
        return rep
    g = grid(wb[sname])

    # 기간
    y = 2026
    mo = wk = None
    for row in g[:5]:
        for cell in row:
            m = _TITLE_RE.search(str(cell or ""))
            if m:
                mo, wk = int(m["m"]), int(m["w"])
                break
    rep.period = PeriodKey("weekly", y, mo, wk, label=f"{y}년 {mo}월 {wk}주" if mo else filename)
    if mo is None:
        rep.warn(f"기간 파싱 실패(파일명 대체): {filename}")

    _summary(g, rep)

    # 팀 시트 상세 (지역/불량/장비) — 신양식 파서 로직 상당부분 재사용 가능하나
    # 구양식 팀시트는 상단에 '주요내용' 서술 블록이 있어 오프셋이 다르다.
    for team, sheet in (("K", "K테크솔루션"), ("M", "M테크솔루션"), ("D", "D테크솔루션")):
        nm = _find(wb, sheet)
        if not nm:
            rep.warn(f"시트 없음: {sheet}")
            continue
        _team_sheet(grid(wb[nm]), team, rep)

    # 지원 AS현황 → svc_case
    nm = _find(wb, "지원 AS현황") or _find(wb, "M·D테크솔루션 지원 AS현황")
    if nm:
        _support_as(grid(wb[nm]), rep)

    return rep


def _find(wb, needle: str) -> str | None:
    for n in wb.sheetnames:
        if needle in n:
            return n
    return None


def _summary(g, rep: ParsedReport) -> None:
    a = find_anchor(g, "구분")
    if not a:
        rep.warn("요약표 앵커 '구분' 없음")
        return
    r0, c0 = a
    for dr in range(1, 8):
        row = g[r0 + dr] if r0 + dr < len(g) else []
        label = clean(row[c0]) if row else None
        team = _TEAM_LABEL.get(label or "")
        if not team:
            if label and "합계" in label:
                break
            continue
        rep.add("svc_summary", team_code=team,
                received=as_int(_c(row, c0, 1)), inbound=as_int(_c(row, c0, 3)),
                revenue_krw=as_int(_c(row, c0, 5)), revenue_krw_ytd=as_int(_c(row, c0, 7)))


def _c(row, base, off):
    i = base + off
    return row[i] if 0 <= i < len(row) else None


def _team_sheet(g, team, rep: ParsedReport) -> None:
    # 지역별
    a = find_anchor(g, "상세 지역별") or find_anchor(g, "지역별")
    if a:
        r0, _ = a
        for dr in range(r0 + 2, min(r0 + 16, len(g))):
            row = g[dr]
            region = clean(row[0]) if row else None
            if region in ("아시아", "CIS", "중동", "아프리카", "중국", "오세아니아", "유럽", "남미"):
                rep.add("svc_region", team_code=team, region=region,
                        total=as_int(row[1]), completed=as_int(row[2]),
                        incomplete=as_int(row[3]), rate=num(row[4]))
            elif region in ("합계", "총계"):
                break
    # 장비 모델별 (K테크 위주, 3-1/3-2/3-3)
    for anchor, group in (("3-1 C-arm", "C-arm"), ("3-2 Mammo", "Mammo"), ("3-3 Dental", "Dental")):
        aa = find_anchor(g, anchor)
        if not aa:
            continue
        r0, _ = aa
        hdr = g[r0 + 1] if r0 + 1 < len(g) else []
        vals = g[r0 + 2] if r0 + 2 < len(g) else []
        for i, model in enumerate(hdr[1:], start=1):
            m = clean(model)
            if m and m != "합계":
                rep.add("equipment_stat", team_code=team, product_group=group,
                        model=m, visit_cnt=as_int(vals[i]) if i < len(vals) else None)


def _support_as(g, rep: ParsedReport) -> None:
    """'금주 | 월누계 | 년누계' 세로 블록 구조. '금주' 블록만 svc_case 로."""
    hdr_row = None
    for r, row in enumerate(g[:6]):
        if any(clean(c) == "조치사항" for c in row):
            hdr_row = r
            break
    if hdr_row is None:
        rep.warn("지원 AS현황: 헤더행('조치사항') 못 찾음")
        return
    hdr = [clean(c) for c in g[hdr_row]]

    def col(*names):
        for nm in names:
            if nm in hdr:
                return hdr.index(nm)
        return None

    ci = {
        "region": col("지역"), "outlet": col("출하처", "국가"),
        "model": col("제품 사양", "제품사양"), "recv": col("접수일"),
        "act": col("조치일"), "action": col("조치사항"),
        "group": col("제품 분류", "제품분류"),
    }
    for row in g[hdr_row + 1:]:
        if not row or ci["model"] is None:
            continue
        model = clean(row[ci["model"]]) if ci["model"] < len(row) else None
        if not model:
            continue
        rep.add("svc_case",
                region=clean(row[ci["region"]]) if ci["region"] is not None else None,
                country=clean(row[ci["outlet"]]) if ci["outlet"] is not None else None,
                product_model=model,
                received_date=as_date(row[ci["recv"]]) if ci["recv"] is not None else None,
                action_date=as_date(row[ci["act"]]) if ci["act"] is not None else None,
                action=clean(row[ci["action"]]) if ci["action"] is not None else None,
                result="완료")
