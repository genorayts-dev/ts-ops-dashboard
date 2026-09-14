"""
monthly: TS본부_월간실적(YYYY년 NN월)*.xlsx

'월간 실적' 표지:
  * 상단에 1월~당월 x (D테크/M테크/K테크/Total) 매트릭스가 3벌:
      서비스(건) / Inbound(건) / AS매출(당월, 누계)  → monthly_trend
  * Ⅱ. 서비스 이슈  (주요 N건 / 다발성 N건, 각 [발생현황][원인분석][조치내용])  → svc_issue
  * Ⅲ. KPI 추진 실적 (구분 | 팀 | 목표 | 내용)                                  → kpi_item

'(D/M/K테크) 서비스 실적' 시트:
  1. 제품별   (Model | 전월미완료 | 당월접수 | 총건수 | 완료 | 미완료 | 완료율 | 누계...)
  2. 지역별
  3. 불량 내역별 (SW/HW/기타 x subtype x 당월/누계)                            → defect_breakdown

'M테크 Raw Data' / 'K테크솔루션 지원 Raw Data':
  No|지역|국가|지원시작일|제품 사양|제품 코드|접수일|조치일|제목|조치사항|불량 원인|결과 → svc_case

TODO(실파일 대조):
  * 표지 매트릭스 열 위치(파일이 넓어 병합 많음) — anchor '당월' 기준 오프셋 확정
  * KPI 시트 'N월 실적 상세' 의 달성률(1/공란) → achieved
"""
from __future__ import annotations

import re

from .schema import ParsedReport, PeriodKey
from .xlsx_util import as_date, as_int, clean, find_all_anchors, find_anchor, grid, load, num

_FILE_RE = re.compile(r"(?P<y>\d{4})\D*?(?P<m>\d{1,2})\s*월")
_FILE_RE2 = re.compile(r"(?P<y>\d{2})\s*년\s*(?P<m>\d{1,2})\s*월")  # '26년 3월'
_MONTH_LABEL = re.compile(r"^(\d{1,2})월$")
_TEAMS = ("D", "M", "K")


def parse_monthly(raw: bytes, filename: str) -> ParsedReport:
    rep = ParsedReport("monthly", PeriodKey("monthly", 2026))
    wb = load(raw)

    m = _FILE_RE.search(filename)
    m2 = _FILE_RE2.search(filename)
    if m:
        y, mo = int(m["y"]), int(m["m"])
    elif m2:
        y, mo = 2000 + int(m2["y"]), int(m2["m"])
    else:
        y = mo = None
        rep.warn(f"파일명 기간 파싱 실패: {filename}")
    if mo:
        rep.period = PeriodKey("monthly", y, mo, label=f"{y}년 {mo:02d}월")

    cover = _find(wb, "월간 실적")
    if cover:
        _cover(grid(wb[cover]), rep)
    else:
        rep.warn("'월간 실적' 표지 시트 없음")

    for team in _TEAMS:
        nm = _find(wb, f"({team}테크) 서비스 실적")
        if nm:
            _team_service(grid(wb[nm]), team, rep)
        else:
            rep.warn(f"시트 없음: ({team}테크) 서비스 실적")

    for nm in wb.sheetnames:
        if "Raw Data" in nm:
            team = "M" if nm.startswith("M") else ("K" if nm.startswith("K") else None)
            _raw_data(grid(wb[nm]), team, rep)

    kpi_sheet = next((n for n in wb.sheetnames if "실적 상세" in n), None)
    if kpi_sheet:
        _kpi(grid(wb[kpi_sheet]), rep)
    else:
        rep.warn("KPI '실적 상세' 시트 없음")

    # 'N월 목표' 시트 (분기 목표 제외) → 계획 항목
    plan_sheet = next((n for n in wb.sheetnames
                       if n.strip().endswith("목표") and "분기" not in n), None)
    if plan_sheet:
        _kpi_plan(grid(wb[plan_sheet]), plan_sheet, rep)

    return rep


_TEAM_CODE = {"D테크": "D", "M테크": "M", "K테크": "K", "TS본부": None, "공통": None}


def _kpi(g, rep: ParsedReport) -> None:
    """
    'N월 실적 상세' 시트: 구분 | 담당 | 월간 목표 | 실적 | 월 달성률 | 바로가기
    구분/담당은 병합되어 첫 행에만 있으므로 forward-fill.
    달성률: '1' → 달성, 공란 → 미달성.
    """
    hr = None
    for r, row in enumerate(g[:15]):
        cells = [clean(c) for c in row]
        if "구분" in cells and ("월 달성률" in cells or "월간 목표" in cells):
            hr = r
            break
    if hr is None:
        rep.warn("KPI 실적 상세: 헤더행 못 찾음")
        return
    hdr = [clean(c) or "" for c in g[hr]]

    def col(*names):
        for nm in names:
            if nm in hdr:
                return hdr.index(nm)
        return None

    c_cat = col("구분")
    c_team = col("담당")
    c_goal = col("월간 목표")
    c_res = col("실적")
    c_ach = col("월 달성률", "달성률")
    if c_cat is None or c_goal is None or c_ach is None:
        rep.warn("KPI 실적 상세: 필요한 열(구분/월간목표/달성률) 못 찾음")
        return

    cat = team = None
    n = 0
    for row in g[hr + 1:]:
        cv = clean(row[c_cat]) if c_cat < len(row) else None
        tv = clean(row[c_team]) if c_team is not None and c_team < len(row) else None
        goal = clean(row[c_goal]) if c_goal < len(row) else None
        if cv:
            cat = cv
        if tv:
            team = tv
        if not goal or goal in ("▶ 돌아가기", "돌아가기"):
            continue
        ach_raw = clean(row[c_ach]) if c_ach < len(row) else None
        achieved = 1.0 if (ach_raw and ach_raw not in ("0", "-", "x", "X")) else 0.0
        rep.add(
            "kpi_item",
            category=cat,
            team_code=_TEAM_CODE.get(team or "", None),
            goal_text=goal,
            result_text=clean(row[c_res]) if c_res is not None and c_res < len(row) else None,
            achieved=achieved,
            is_plan=False,
        )
        n += 1
    if n == 0:
        rep.warn("KPI 실적 상세: 항목 0건")


def _kpi_plan(g, sheet_name: str, rep: ParsedReport) -> None:
    """'N월 목표' 시트: 구분 | 담당 | 월간 목표  (아직 미착수 계획)."""
    mm = re.search(r"(\d{1,2})\s*월", sheet_name)
    plan_month = int(mm.group(1)) if mm else None
    hr = None
    for r, row in enumerate(g[:15]):
        cells = [clean(c) for c in row]
        if "구분" in cells and "월간 목표" in cells:
            hr = r
            break
    if hr is None:
        return
    hdr = [clean(c) or "" for c in g[hr]]
    c_cat, c_team, c_goal = hdr.index("구분"), (hdr.index("담당") if "담당" in hdr else 1), hdr.index("월간 목표")
    cat = team = None
    for row in g[hr + 1:]:
        cv = clean(row[c_cat]) if c_cat < len(row) else None
        tv = clean(row[c_team]) if c_team < len(row) else None
        goal = clean(row[c_goal]) if c_goal < len(row) else None
        if cv:
            cat = cv
        if tv:
            team = tv
        if not goal or "돌아가기" in goal:
            continue
        rep.add("kpi_item", category=cat, team_code=_TEAM_CODE.get(team or "", None),
                goal_text=goal, result_text=None, achieved=None,
                is_plan=True, plan_month=plan_month)


def _find(wb, needle: str) -> str | None:
    for n in wb.sheetnames:
        if needle in n:
            return n
    return None


def _cover(g, rep: ParsedReport) -> None:
    """1월~당월 팀별 추이 3벌(서비스/Inbound/AS매출) + 이슈 + KPI."""
    # ---- 월별 추이 매트릭스 ----
    # 표지 우측에 3개 블록이 나란히: [월 | D | M | K | Total] × (서비스 / Inbound / AS매출).
    # 3블록의 '월' 라벨은 서로 다른 열에 있고, 같은 행에 셋이 함께 온다.
    # → '월' 라벨 셀을 전부 찾고, '열' 로 클러스터링해서 왼→오 순서로 service/inbound/revenue.
    from collections import Counter

    month_cells: list[tuple[int, int, int]] = []  # (row, col, month)
    for r, row in enumerate(g):
        for c, v in enumerate(row):
            mm = _MONTH_LABEL.match(str(v or "").strip())
            if mm:
                month_cells.append((r, c, int(mm.group(1))))
    col_freq = Counter(c for _, c, _ in month_cells)
    label_cols = sorted(c for c, n in col_freq.items() if n >= 4)  # 최소 4개월치 있는 열만
    metric_names = ["service_cnt", "inbound_cnt", "revenue_krw"]
    y = rep.period.year
    for mi, mc in enumerate(label_cols[:3]):
        metric = metric_names[mi]
        for (r, c, month) in month_cells:
            if c != mc:
                continue
            vals = [num(x) for x in g[r][c + 1:c + 6] if num(x) is not None]
            if len(vals) >= 3:
                for team, val in zip(_TEAMS, vals[:3]):
                    rep.add("monthly_trend", year=y, month=month, team_code=team,
                            **{metric: as_int(val)})
    if not label_cols:
        rep.warn("표지 월별 추이 매트릭스 못 읽음")

    # ---- 서비스 이슈 ----
    a = find_anchor(g, "서비스 이슈")
    if a:
        r0, _ = a
        kind = None
        cur = None
        for row in g[r0 + 1:r0 + 60]:
            t = " ".join(clean(c) or "" for c in row).strip()
            if not t:
                continue
            if t.startswith("주요 이슈") or "주요 이슈" in t:
                kind = "주요"
            elif "다발성" in t:
                kind = "다발성"
            elif re.match(r"^[①②③④⑤]", t):
                if cur:
                    rep.add("svc_issue", kind=kind, **cur)
                cur = {"title": re.sub(r"^[①②③④⑤]\s*", "", t.split("▶")[0]).strip(),
                       "occurrence": None, "cause": None, "action": None}
            elif cur and "[발생현황]" in t:
                cur["occurrence"] = t.split("]", 1)[-1].strip()
            elif cur and ("[원인분석]" in t or "[대응방향]" in t):
                cur["cause"] = t.split("]", 1)[-1].strip()
            elif cur and ("[조치내용]" in t or "[조치계획]" in t):
                cur["action"] = t.split("]", 1)[-1].strip()
            elif t.startswith("Ⅲ.") or "KPI 추진" in t:
                break
        if cur:
            rep.add("svc_issue", kind=kind, **cur)


def _team_service(g, team: str, rep: ParsedReport) -> None:
    a = find_anchor(g, "3. 불량 내역별")
    if not a:
        rep.warn(f"[{team}] '3. 불량 내역별' 없음")
        return
    r0, _ = a
    cat = None
    for row in g[r0 + 1:r0 + 60]:
        first = clean(row[0]) if row else None
        if first in ("S/W", "H/W", "기타"):
            cat = {"S/W": "SW", "H/W": "HW", "기타": "지원"}[first]
        if first == "총계":
            break
        # subtype 은 col 2 또는 3, 당월/누계는 뒤쪽 숫자 2개
        subtype = clean(row[2]) if len(row) > 2 and clean(row[2]) else (
            clean(row[3]) if len(row) > 3 else None)
        nums = [as_int(x) for x in row if num(x) is not None]
        if cat and subtype and subtype not in ("계",) and len(nums) >= 2:
            rep.add("defect_breakdown", team_code=team, category=cat, subtype=subtype,
                    cnt_period=nums[-2], cnt_ytd=nums[-1])


def _raw_data(g, team: str | None, rep: ParsedReport) -> None:
    hdr_row = None
    for r, row in enumerate(g[:5]):
        cells = [clean(c) for c in row]
        if "조치사항" in cells and ("국가" in cells or "지역" in cells):
            hdr_row = r
            break
    if hdr_row is None:
        rep.warn(f"Raw Data({team}): 헤더행 못 찾음")
        return
    hdr = [clean(c) or "" for c in g[hdr_row]]

    def col(*names):
        for nm in names:
            for i, h in enumerate(hdr):
                if h == nm or h.replace(" ", "") == nm.replace(" ", ""):
                    return i
        return None

    idx = {
        "seq_no": col("No"), "region": col("지역"), "country": col("국가"),
        "install_date": col("지원시작일", "설치일"),
        "product_model": col("제품 사양", "모델"), "product_code": col("제품 코드", "제조번호"),
        "received_date": col("접수일"), "action_date": col("조치일"),
        "title": col("제목", "증상"), "action": col("조치사항"),
        "defect_cause": col("불량 원인", "원인"), "result": col("결과", "상태"),
    }

    def get(row, key, conv=clean):
        i = idx[key]
        if i is None or i >= len(row):
            return None
        return conv(row[i])

    for row in g[hdr_row + 1:]:
        if not row or get(row, "country") is None and get(row, "product_model") is None:
            continue
        rep.add("svc_case", team_code=team,
                seq_no=get(row, "seq_no", as_int),
                region=get(row, "region"), country=get(row, "country"),
                install_date=get(row, "install_date", as_date),
                product_model=get(row, "product_model"),
                product_code=get(row, "product_code"),
                received_date=get(row, "received_date", as_date),
                action_date=get(row, "action_date", as_date),
                title=get(row, "title"), action=get(row, "action"),
                defect_cause=get(row, "defect_cause"),
                result=get(row, "result") or "완료")
