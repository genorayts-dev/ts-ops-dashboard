"""
geno-one(사내 ERP) AS관리(/aspart) export 파서.

원본 헤더(2026-09-17 확인, 40컬럼, 헤더 그대로):
    No|담당구분|딜러사|고객사|이슈|제품명|보증기간 만료일|조치/출장자|시리얼 넘버|접수일|
    조치일|Service Status|Contact Point|국가(딜러사)|기간별|조치 후 점검|결과|불량증상|
    상세설명|유형|국가(고객사)|부품변경내역|조치사항|수리비|구분(서비스, 고객불만)|후속조치|
    분석표 대분류|분석표 중분류|분석표 소분류|조치분류|원인분석|UDI|보증기간|유상/무상|
    이상사례|구분|출하일|지역(분석표)|불량구분(분석표)|청구내역

해외(M/D)만 존재 — K국내 행 0건. as_ticket(기존 통합시트 md_service)과 스코프가 달라
별도 테이블(geno_one_ticket)에 격리 적재한다(1:1 매핑 아닐 수 있어 나중에 교차검증).
매 동기화가 현재 시점 전체 스냅샷이므로 scope_key 하나로 고정해 재동기화 시 이전 batch
가 자동 대체되게 한다(v_latest_batch).
"""
from __future__ import annotations

import re

from .schema import ParsedReport, PeriodKey
from .xlsx_util import as_date, clean, grid, load, num

_CUR_RE = re.compile(r"[A-Z]{3}")


def _c(v):
    s = clean(v)
    return None if s in (None, "-") else s


def _repair_cost(v):
    """원본 '5,115 USD' 형태 → (금액, 통화)."""
    s = _c(v)
    if s is None:
        return None, None
    m = _CUR_RE.search(s)
    cur = m.group(0) if m else None
    return num(s.replace(cur, "") if cur else s), cur


def parse_geno_one_aspart(raw: bytes, filename: str) -> ParsedReport:
    wb = load(raw)
    g = grid(wb[wb.sheetnames[0]])
    if not g:
        rep = ParsedReport("geno_one_aspart", PeriodKey("consolidated", 2026, label="AS관리 (geno-one)"))
        rep.warn("geno-one AS관리 시트가 비어 있습니다")
        return rep

    header = [clean(h) or "" for h in g[0]]
    idx = {h: i for i, h in enumerate(header) if h}

    def col(row, name):
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else None

    rep = ParsedReport("geno_one_aspart", PeriodKey("consolidated", 2026, label="AS관리 (geno-one)"))
    rep.scope_key = "geno_one_aspart"

    n = 0
    for row in g[1:]:
        if not any(clean(x) for x in row):
            continue
        repair_cost, repair_currency = _repair_cost(col(row, "수리비"))
        rep.add(
            "geno_one_ticket",
            seq_no=_c(col(row, "No")),
            charge_type=_c(col(row, "담당구분")),
            dealer=_c(col(row, "딜러사")),
            customer=_c(col(row, "고객사")),
            issue=_c(col(row, "이슈")),
            product_name=_c(col(row, "제품명")),
            warranty_expire=as_date(col(row, "보증기간 만료일")),
            engineer=_c(col(row, "조치/출장자")),
            serial_no=_c(col(row, "시리얼 넘버")),
            received_date=as_date(col(row, "접수일")),
            action_date=as_date(col(row, "조치일")),
            service_status=_c(col(row, "Service Status")),
            contact_point=_c(col(row, "Contact Point")),
            dealer_country=_c(col(row, "국가(딜러사)")),
            period_bucket=_c(col(row, "기간별")),
            post_check=_c(col(row, "조치 후 점검")),
            result=_c(col(row, "결과")),
            symptom=_c(col(row, "불량증상")),
            detail=_c(col(row, "상세설명")),
            ticket_type=_c(col(row, "유형")),
            customer_country=_c(col(row, "국가(고객사)")),
            parts_changed=_c(col(row, "부품변경내역")),
            action_taken=_c(col(row, "조치사항")),
            repair_cost=repair_cost,
            repair_currency=repair_currency,
            category=_c(col(row, "구분(서비스, 고객불만)")),
            followup=_c(col(row, "후속조치")),
            line_major=_c(col(row, "분석표 대분류")),
            line_mid=_c(col(row, "분석표 중분류")),
            line_minor=_c(col(row, "분석표 소분류")),
            fix_class=_c(col(row, "조치분류")),
            root_cause=_c(col(row, "원인분석")),
            udi=_c(col(row, "UDI")),
            warranty_period=_c(col(row, "보증기간")),
            warranty_paid=_c(col(row, "유상/무상")),
            adverse_event=_c(col(row, "이상사례")),
            case_class=_c(col(row, "구분")),
            ship_date=as_date(col(row, "출하일")),
            region_analysis=_c(col(row, "지역(분석표)")),
            defect_class_analysis=_c(col(row, "불량구분(분석표)")),
            billing_note=_c(col(row, "청구내역")),
        )
        n += 1
    if not n:
        rep.warn("geno-one AS관리 데이터 0건")
    return rep
