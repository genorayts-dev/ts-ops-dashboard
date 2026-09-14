from __future__ import annotations

from .xlsx_util import load


def detect_format(raw: bytes, filename: str) -> str:
    """시트 이름만 보고 3종 중 하나로 분기. 파일명은 보조 신호."""
    wb = load(raw)
    names = [s.strip() for s in wb.sheetnames]
    joined = " | ".join(names)

    def has_prefix(*prefixes: str) -> bool:
        return any(n.startswith(p) for n in names for p in prefixes)

    # gsheet_master: 통합 구글 시트 (AS 매출/채권/서비스 탭 묶음)
    #   탭 이름 규칙이 바뀔 수 있어(예: 'AS 매출 K테크'→'K AS매출') 옛/새 이름을 모두 인식.
    nospace = [n.replace(" ", "") for n in names]
    _gs_old = sum(any(k in n for n in nospace)
                  for k in ("AS매출K", "AS매출해외", "AS발송해외", "AS채권", "MD서비스", "MD방문"))
    _gs_new = sum(any(k in n for n in nospace)
                  for k in ("AS매출", "채권", "유지보수", "MDAS"))
    if _gs_old >= 2 or _gs_new >= 3:
        return "gsheet_master"

    # gsheet_plan: 2026 사업계획(업무 세부 실행계획) 구글 시트
    if any(("사업계획" in n) or ("진행현황" in n) or ("실행계획" in n) for n in nospace):
        for s in wb.worksheets:
            for row in s.iter_rows(min_row=1, max_row=8, values_only=True):
                if any(v and "실행계획" in str(v) for v in row):
                    return "gsheet_plan"

    # monthly: '월간 실적' 표지 + 팀별 '서비스 실적'
    if "월간 실적" in names or "월간실적" in filename.replace(" ", ""):
        if has_prefix("(D테크) 서비스 실적", "(M테크) 서비스 실적", "(K테크) 서비스 실적") or "월간" in filename:
            return "monthly"

    # weekly_new: '0. 주간보고(TS본부)' + '1. D테크' 류
    if any(n.startswith("0. 주간보고") for n in names) or has_prefix("1. D테크", "2. M테크", "3. K테크"):
        return "weekly_new"

    # weekly_old: 다중시트 주간회의록
    if "TS본부 주간업무보고" in names or "주간회의록(양식)" in names or "K테크솔루션" in names:
        return "weekly_old"

    # as_report: AS 접수처리대장 (D/M/K/부산)
    if any(n.strip().startswith(("접수처리대장", "접수확인서", "AS접수처리대장")) for n in names):
        return "as_report"
    fn = filename.replace(" ", "")
    if "AS접수처리대장" in fn or "AS보고서" in fn or "AS접수처리" in fn:
        return "as_report"

    raise ValueError(f"양식 판별 실패: sheets=[{joined}] file={filename!r}")
