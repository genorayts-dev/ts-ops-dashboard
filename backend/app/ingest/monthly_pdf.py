"""
monthly_pdf: 월간실적 발표 PDF(슬라이드) → kpi_item 만 추출.

PDF 는 발표 자료라서 팀별 월매출(monthly_trend) 등 백데이터는 없다.
별첨 A3(항목별 상세) 페이지에서 KPI 추진 실적만 뽑는다:

  D테크 · 서비스 고도화
  A3-1. 서비스 영상 제작
  연간 목표
  서비스 영상 제작 (연간 총 25건)
  7월 목표 → 실적
  ... → 영상 2건 제작 ...
  누적 진행률
  25건 중 13건 (60%)
  실적 상세
  ...

scope_key='monthly' → 같은 달의 정식 xlsx 가 올라오면 이 batch 를 대체.
"""
from __future__ import annotations

import re

from .schema import ParsedReport, PeriodKey

_TEAM = {"D": "D", "M": "M", "K": "K"}
_CAT = {
    "서비스 고도화": "서비스 고도화",
    "서비스 상품화": "서비스 상품화",
    "조직 역량 강화": "조직역량강화",
    "조직역량강화": "조직역량강화",
}

_BLOCK = re.compile(
    r"(?P<team>[DMK])테크\s*[·ㆍ∙・]\s*(?P<cat>서비스 고도화|서비스 상품화|조직 ?역량 ?강화)\s*\n"
    r"A3-\d+\.\s*(?P<title>.+?)\n"
    r"연간\s*목표\s*\n(?P<goal>.+?)\n"
    r"\s*\d{1,2}월\s*목표\s*(?:→|->|~|-|�)\s*실적\s*\n(?P<result>.+?)\n"
    r"\s*누적\s*진행률\s*\n(?P<prog>.+?)\n"
    r"\s*실적\s*상세",
    re.S,
)


def _extract_text(raw: bytes) -> str:
    from pypdf import PdfReader
    import io

    r = PdfReader(io.BytesIO(raw))
    return "\n".join((p.extract_text() or "") for p in r.pages)


def parse_monthly_pdf(raw: bytes, filename: str) -> ParsedReport:
    fn = filename.replace(" ", "")
    ym = re.search(r"(20\d{2})년?(\d{1,2})월", fn) or re.search(r"(20\d{2})[.\-_/](\d{1,2})", fn)
    year = int(ym.group(1)) if ym else None
    month = int(ym.group(2)) if ym else None

    try:
        text = _extract_text(raw)
    except Exception as e:  # noqa: BLE001
        rep = ParsedReport("monthly_pdf", PeriodKey("monthly", year or 2026, month))
        rep.scope_key = "monthly"
        rep.warn(f"PDF 텍스트 추출 실패: {type(e).__name__}: {e}")
        return rep

    # 파일명 파싱 실패 시 본문에서 보완: 'Ⅰ. 7월 서비스 운영 실적' / '7월 목표' / '2026.08.11'
    if month is None:
        mt = re.search(r"([1-9]|1[0-2])\s*월\s*(?:서비스\s*운영\s*실적|목표|월간실적|핵심\s*성과)", text)
        if mt:
            month = int(mt.group(1))
    if year is None:
        yt = re.search(r"(20\d{2})[.\-]\d{1,2}[.\-]\d{1,2}", text) or re.search(r"(20\d{2})년", text)
        year = int(yt.group(1)) if yt else 2026

    rep = ParsedReport(
        "monthly_pdf",
        PeriodKey("monthly", year, month,
                  label=f"{year}년 {month:02d}월" if month else f"{year}년"),
    )
    rep.scope_key = "monthly"
    if month is None:
        rep.warn("월간 PDF: 대상 월을 판별하지 못했습니다 (파일명/본문 모두 실패)")

    # 페이지4 요약: 'N월 목표 X건 100% 달성' / '누적 Y건'
    msum = re.search(r"(\d{1,2})월\s*목표\s*\n?\s*(\d+)\s*건", text)
    mcum = re.search(r"누적\s*(\d+)\s*건\s*(\d+)%", text)

    n = 0
    for m in _BLOCK.finditer(text):
        team = _TEAM.get(m.group("team"))
        cat = _CAT.get(re.sub(r"\s+", " ", m.group("cat")).replace("조직 역량 강화", "조직역량강화"),
                       re.sub(r"\s+", " ", m.group("cat")))
        goal = m.group("goal").strip()
        result = re.sub(r"\s*\n\s*", " ", m.group("result").strip())
        prog = re.sub(r"\s*\n\s*", " ", m.group("prog").strip())
        pct = re.search(r"(\d+)\s*%", prog)
        cum_ratio = re.search(r"(\d+)\s*건\s*중\s*(\d+)\s*건", prog)

        # 월 달성: 발표자료 기준 해당 월 목표는 100% 달성으로 기재됨
        achieved = 1.0
        result_text = f"{result}  ·  누적 진행률 {prog}"

        rep.add(
            "kpi_item",
            category=cat,
            team_code=team,
            goal_text=goal,
            result_text=result_text,
            achieved=achieved,
            is_plan=False,
        )
        n += 1

    if n == 0:
        rep.warn("월간 PDF: KPI 항목(별첨 A3)을 찾지 못했습니다 — 슬라이드 형식 확인 필요")
    elif msum and int(msum.group(2)) and n < int(msum.group(2)) - 3:
        rep.warn(f"월간 PDF: KPI {n}건만 추출 (요약상 {msum.group(2)}건) — 일부 누락 가능")

    return rep
