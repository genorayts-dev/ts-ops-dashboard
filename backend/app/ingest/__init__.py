"""
엑셀 업로드 → 정규화 적재 파이프라인.

흐름 (routers/ingest.py 에서 호출):
    raw_bytes ─▶ detect_format()  ─▶ 'weekly_new' | 'weekly_old' | 'monthly'
              ─▶ parse_*()        ─▶ ParsedReport(period + facts[])
              ─▶ persist()        ─▶ report_period upsert
                                     upload_batch insert (트리거가 이전 batch supersede)
                                     fact 테이블 bulk insert (batch_id 스코프)

핵심 원칙
  * 파서는 '있는 그대로' 읽고, 못 읽은 셀은 warnings 에 남긴다(예외로 죽지 않음).
  * 원화 환산은 fx_plan(연도별 사업계획 환율)으로 일괄. 원본에 이미 환산액이 있으면 그대로.
  * seq_no / product_code 로 svc_case 중복은 batch 내에서만 관리(배치 교체 = 전량 재적재).
"""

from .detect import detect_format
from .persist import persist
from .schema import ParsedReport, Fact

__all__ = ["detect_format", "persist", "ParsedReport", "Fact", "parse"]


def parse(raw: bytes, filename: str) -> ParsedReport:
    if filename.lower().endswith(".pdf"):
        from .monthly_pdf import parse_monthly_pdf
        return parse_monthly_pdf(raw, filename)
    fmt = detect_format(raw, filename)
    if fmt == "weekly_new":
        from .weekly_new import parse_weekly_new
        return parse_weekly_new(raw, filename)
    if fmt == "weekly_old":
        from .weekly_old import parse_weekly_old
        return parse_weekly_old(raw, filename)
    if fmt == "monthly":
        from .monthly import parse_monthly
        return parse_monthly(raw, filename)
    if fmt == "as_report":
        from .as_report import parse_as_report
        return parse_as_report(raw, filename)
    if fmt == "gsheet_master":
        from .gsheet_master import parse_gsheet_master
        return parse_gsheet_master(raw, filename)
    if fmt == "gsheet_plan":
        from .gsheet_plan import parse_gsheet_plan
        return parse_gsheet_plan(raw, filename)
    raise ValueError(f"알 수 없는 양식: {filename}")
