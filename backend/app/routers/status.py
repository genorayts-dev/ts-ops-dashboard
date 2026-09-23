"""
'현황' 대시보드 — 통합 구글시트의 '국내(K테크) 현황' / '해외(M·D테크) 현황' 탭을 대체.
그 두 탭은 구글시트 피벗테이블로 구성돼 있어 공개 xlsx export 시 피벗 결과 셀이
비어서 내려온다(요약 카드만 수식이라 값이 살아있음) → 같은 원본 데이터(as_ticket/
receivable/maintenance_contract)로 이 라우터가 직접 재계산해 동일한 구성을 제공한다.

S/W·H/W 이분류는 원본에 없어 fix_class 텍스트로 근사한다(Software/Firmware/Theia/
Windows 계열만 S/W, 나머지는 H/W — 사용자 확인, 2026-09-16).

주차 경계: 원본 시트가 '해당 주 목요일이 속한 달' 기준을 쓰던 것에 맞춰(2026-09-17
사용자 지시), 여기서는 아예 주 자체를 목요일 시작으로 재정의한다(목~다음 수요일).
ISODOW(월=1..일=7) 기준 목요일=4 이므로 week_start = date - ((ISODOW(date)-4+7) % 7).
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db

router = APIRouter(prefix="/api/status", tags=["status"])

_LBT = "JOIN v_latest_batch lb ON lb.batch_id = t.batch_id"
_LBR = "JOIN v_latest_batch lb ON lb.batch_id = r.batch_id"
_LBM = "JOIN v_latest_batch lb ON lb.batch_id = mc.batch_id"
_FXR = ("CASE upper(coalesce(r.currency,'')) WHEN 'USD' THEN 1380 WHEN 'EUR' THEN 1640 "
        "WHEN 'JPY' THEN 9.4 WHEN 'CNY' THEN 195 ELSE 1 END")
_FXM = ("CASE upper(coalesce(mc.currency,'KRW')) WHEN 'USD' THEN 1380 WHEN 'EUR' THEN 1640 "
        "WHEN 'JPY' THEN 9.4 WHEN 'CNY' THEN 195 ELSE 1 END")
#   S/W = Software, H/W = Hardware (사용자 확인). 불량구분(fix_class) 원본 값 중
#   소프트웨어/펌웨어 성격이 뚜렷한 것만 S/W로 분류하고 나머지(기구부/PC/PCB/Generator/
#   반제품/Detector/영상품질/OP/사용자교육/Calibration/기타 등)는 전부 H/W.
_SW = ("(t.fix_class ILIKE '%%software%%' OR t.fix_class ILIKE '%%s/w%%' "
       "OR t.fix_class ILIKE '%%소프트%%' OR t.fix_class ILIKE '%%firmware%%' "
       "OR t.fix_class ILIKE '%%theia%%' OR t.fix_class ILIKE '%%windows%%')")
_SWHW = f"(CASE WHEN {_SW} THEN 'S/W' ELSE 'H/W' END)"
# 해외(M/D)는 팀이 섞여있어 S/W·H/W 만 따로 보면 어느 팀 건인지 알 수 없어 헷갈림
# (예: 특정 주 M 접수 0건인데 S/W 건수만 보면 M 것처럼 보임) → 팀명을 합쳐서 표기.
_SWHW_TEAM = f"(t.org || '·' || {_SWHW})"

# 담당자(engineer) 공란인 건은 팀별로 몰려있는 경우가 많아(예: D테크 MD서비스 건은
# 담당자 미기재가 관행) '(미상)' 대신 소속 팀을 밝혀서 표기.
_ENG = "coalesce(nullif(t.engineer,''), t.org || '테크(담당자 미기재)')"

# 주차 시작일(목요일 기준). c 는 날짜 컬럼 표현식.
_WK = "({c}::date - ((EXTRACT(ISODOW FROM {c})::int - 4 + 7) % 7))"
# '오늘이 속한 주'의 시작일(목요일 기준) — 카드의 금주/전주 경계에 사용.
_CUR_WK = "(CURRENT_DATE - ((EXTRACT(ISODOW FROM CURRENT_DATE)::int - 4 + 7) % 7))"


def _week_rows(db: Session, sql: str, params: dict):
    return db.execute(text(sql), params).mappings().all()


@router.get("/domestic")
def domestic(db: Session = Depends(get_db), year: int = 2026, weeks: int = 12):
    """국내(K테크) 현황 — K AS매출(src='k_dom') · K 채권 · K 유지보수 기반."""
    base = f"FROM as_ticket t {_LBT} WHERE t.org = 'K' AND t.src = 'k_dom'"

    card = db.execute(text(f"""
        SELECT
          (SELECT count(*) {base}
             AND t.received_date >= {_CUR_WK}
             AND t.received_date <  {_CUR_WK} + 7) AS week_n,
          (SELECT count(*) {base}
             AND t.received_date >= {_CUR_WK} - 7
             AND t.received_date <  {_CUR_WK}) AS last_week_n,
          (SELECT count(*) {base} AND t.received_date >= date_trunc('month', CURRENT_DATE)::date
             AND t.received_date < (date_trunc('month', CURRENT_DATE) + INTERVAL '1 month')::date) AS month_n,
          (SELECT count(*) {base} AND EXTRACT(YEAR FROM t.received_date) = :y) AS ytd_n,
          (SELECT count(*) {base} AND t.warranty = '유상' AND EXTRACT(YEAR FROM t.received_date) = :y) AS paid_n,
          (SELECT sum(coalesce(t.repair_amount_krw,0))::bigint {base}
             AND EXTRACT(YEAR FROM t.action_date) = :y) AS revenue_krw
    """), {"y": year}).mappings().one()

    recv = db.execute(text(f"""
        SELECT sum(coalesce(r.balance,0) * {_FXR})::bigint bal_krw
        FROM receivable r {_LBR} WHERE r.team_code = 'K'
    """)).scalar() or 0

    maint = db.execute(text(f"""
        SELECT sum(mc.monthly_fee * {_FXM})::bigint
        FROM maintenance_contract mc {_LBM}
        WHERE mc.active AND mc.team_code = 'K'
          AND mc.contract_on <= (date_trunc('month', CURRENT_DATE) + INTERVAL '1 month - 1 day')::date
          AND (mc.expires_on IS NULL OR mc.expires_on >= date_trunc('month', CURRENT_DATE)::date)
    """)).scalar() or 0

    cards = {**dict(card), "recv_balance_krw": int(recv), "maint_month_krw": int(maint)}

    w1 = _week_rows(db, f"""
        SELECT {_WK.format(c='t.received_date')} AS week, coalesce(nullif(t.product_line,''),'기타') k, count(*) n
        {base} AND t.received_date >= CURRENT_DATE - (:weeks * 7 || ' days')::interval
        GROUP BY 1, 2 ORDER BY 1, 2
    """, {"weeks": weeks})
    w2 = _week_rows(db, f"""
        SELECT {_WK.format(c='t.received_date')} AS week, {_SWHW} k, count(*) n
        {base} AND t.received_date >= CURRENT_DATE - (:weeks * 7 || ' days')::interval
        GROUP BY 1, 2 ORDER BY 1, 2
    """, {"weeks": weeks})
    w3 = _week_rows(db, f"""
        SELECT {_WK.format(c='t.action_date')} AS week, sum(coalesce(t.repair_amount_krw,0))::bigint krw
        {base} AND t.action_date >= CURRENT_DATE - (:weeks * 7 || ' days')::interval
        GROUP BY 1 ORDER BY 1
    """, {"weeks": weeks})

    m1 = _week_rows(db, f"""
        SELECT EXTRACT(MONTH FROM t.received_date)::int mo, coalesce(nullif(t.product_line,''),'기타') k, count(*) n
        {base} AND EXTRACT(YEAR FROM t.received_date) = :y GROUP BY 1, 2 ORDER BY 1, 2
    """, {"y": year})
    m2 = _week_rows(db, f"""
        SELECT EXTRACT(MONTH FROM t.received_date)::int mo, coalesce(nullif(t.warranty,''),'기타') k, count(*) n
        {base} AND EXTRACT(YEAR FROM t.received_date) = :y GROUP BY 1, 2 ORDER BY 1, 2
    """, {"y": year})
    m3 = _week_rows(db, f"""
        SELECT EXTRACT(MONTH FROM t.action_date)::int mo, sum(coalesce(t.repair_amount_krw,0))::bigint krw
        {base} AND EXTRACT(YEAR FROM t.action_date) = :y GROUP BY 1 ORDER BY 1
    """, {"y": year})

    c1 = _week_rows(db, f"""
        SELECT coalesce(nullif(t.product_line,''),'기타') line, coalesce(nullif(t.warranty,''),'기타') warranty, count(*) n
        {base} AND EXTRACT(YEAR FROM t.received_date) = :y GROUP BY 1, 2 ORDER BY 3 DESC
    """, {"y": year})
    c2 = _week_rows(db, f"""
        SELECT {_SWHW} k, count(*) n
        {base} AND EXTRACT(YEAR FROM t.received_date) = :y GROUP BY 1 ORDER BY 2 DESC
    """, {"y": year})
    c3 = _week_rows(db, f"""
        SELECT {_ENG} engineer, count(*) n, sum(coalesce(t.repair_amount_krw,0))::bigint krw
        {base} AND EXTRACT(YEAR FROM t.received_date) = :y
        GROUP BY 1 ORDER BY 2 DESC LIMIT 20
    """, {"y": year})
    c1_etc = _week_rows(db, f"""
        SELECT coalesce(nullif(t.product_model,''),'(제품명 미기재)') model, count(*) n
        {base} AND EXTRACT(YEAR FROM t.received_date) = :y
          AND coalesce(nullif(t.product_line,''),'기타') = '기타'
        GROUP BY 1 ORDER BY 2 DESC
    """, {"y": year})

    return {"cards": cards,
            "w1": w1, "w2": w2, "w3": w3, "m1": m1, "m2": m2, "m3": m3,
            "c1": c1, "c1_etc": c1_etc, "c2": c2, "c3": c3}


@router.get("/overseas")
def overseas(db: Session = Depends(get_db), year: int = 2026, weeks: int = 12):
    """해외(M·D테크) 현황 — MD AS(src='md_service') · MD 매출(src='overseas_ship') · M/D 채권 기반."""
    svc = f"FROM as_ticket t {_LBT} WHERE t.src = 'md_service'"
    ship = f"FROM as_ticket t {_LBT} WHERE t.src = 'overseas_ship'"

    card = db.execute(text(f"""
        SELECT
          (SELECT count(*) {svc}
             AND t.received_date >= {_CUR_WK}
             AND t.received_date <  {_CUR_WK} + 7) AS week_n,
          (SELECT count(*) {svc}
             AND t.received_date >= {_CUR_WK} - 7
             AND t.received_date <  {_CUR_WK}) AS last_week_n,
          (SELECT count(*) {svc} AND t.received_date >= date_trunc('month', CURRENT_DATE)::date
             AND t.received_date < (date_trunc('month', CURRENT_DATE) + INTERVAL '1 month')::date) AS month_n,
          (SELECT count(*) {svc} AND EXTRACT(YEAR FROM t.received_date) = :y) AS ytd_n,
          (SELECT count(DISTINCT t.country) {svc} AND t.country IS NOT NULL
             AND EXTRACT(YEAR FROM t.received_date) = :y) AS countries_n,
          (SELECT count(*) {ship} AND EXTRACT(YEAR FROM t.action_date) = :y) AS ship_n,
          (SELECT sum(coalesce(t.repair_amount,0)) {ship} AND t.repair_currency = 'USD'
             AND EXTRACT(YEAR FROM t.action_date) = :y) AS ship_usd
    """), {"y": year}).mappings().one()

    recv_usd = db.execute(text(f"""
        SELECT sum(coalesce(r.balance,0)) FROM receivable r {_LBR}
        WHERE r.team_code IN ('M','D') AND upper(coalesce(r.currency,'')) = 'USD'
    """)).scalar() or 0

    cards = {**dict(card), "recv_balance_usd": float(recv_usd)}

    w1 = _week_rows(db, f"""
        SELECT {_WK.format(c='t.received_date')} AS week, t.org k, count(*) n
        {svc} AND t.received_date >= CURRENT_DATE - (:weeks * 7 || ' days')::interval
        GROUP BY 1, 2 ORDER BY 1, 2
    """, {"weeks": weeks})
    #  팀을 나눠 보여줘야 "M 접수 0건인데 S/W 는 2건" 같은 혼선이 안 생긴다(그 2건은 D 것).
    w2 = _week_rows(db, f"""
        SELECT {_WK.format(c='t.received_date')} AS week, {_SWHW_TEAM} k, count(*) n
        {svc} AND t.received_date >= CURRENT_DATE - (:weeks * 7 || ' days')::interval
        GROUP BY 1, 2 ORDER BY 1, 2
    """, {"weeks": weeks})
    w3 = _week_rows(db, f"""
        SELECT {_WK.format(c='t.action_date')} AS week, count(*) n,
               sum(coalesce(t.repair_amount_krw,0))::bigint krw
        {ship} AND t.action_date >= CURRENT_DATE - (:weeks * 7 || ' days')::interval
        GROUP BY 1 ORDER BY 1
    """, {"weeks": weeks})

    m1 = _week_rows(db, f"""
        SELECT EXTRACT(MONTH FROM t.received_date)::int mo, t.org k, count(*) n
        {svc} AND EXTRACT(YEAR FROM t.received_date) = :y GROUP BY 1, 2 ORDER BY 1, 2
    """, {"y": year})
    m2 = _week_rows(db, f"""
        SELECT EXTRACT(MONTH FROM t.received_date)::int mo, coalesce(nullif(t.product_line,''),'기타') k, count(*) n
        {svc} AND EXTRACT(YEAR FROM t.received_date) = :y GROUP BY 1, 2 ORDER BY 1, 2
    """, {"y": year})
    m3 = _week_rows(db, f"""
        SELECT EXTRACT(MONTH FROM t.action_date)::int mo, count(*) n,
               sum(coalesce(t.repair_amount_krw,0))::bigint krw
        {ship} AND EXTRACT(YEAR FROM t.action_date) = :y GROUP BY 1 ORDER BY 1
    """, {"y": year})

    c1 = _week_rows(db, f"""
        SELECT coalesce(nullif(t.product_line,''),'기타') line, coalesce(nullif(t.warranty,''),'기타') warranty, count(*) n
        {svc} AND EXTRACT(YEAR FROM t.received_date) = :y GROUP BY 1, 2 ORDER BY 3 DESC
    """, {"y": year})
    #  누계(C2)도 W2/M2 와 같은 이유로 팀별로 쪼갠다.
    c2 = _week_rows(db, f"""
        SELECT {_SWHW_TEAM} k, count(*) n
        {svc} AND EXTRACT(YEAR FROM t.received_date) = :y GROUP BY 1 ORDER BY 2 DESC
    """, {"y": year})
    c3 = _week_rows(db, f"""
        SELECT coalesce(nullif(t.country,''),'(미상)') country, count(*) n
        {svc} AND EXTRACT(YEAR FROM t.received_date) = :y AND t.country IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC LIMIT 25
    """, {"y": year})
    c4 = _week_rows(db, f"""
        SELECT {_ENG} engineer, count(*) n
        {svc} AND EXTRACT(YEAR FROM t.received_date) = :y GROUP BY 1 ORDER BY 2 DESC LIMIT 20
    """, {"y": year})
    c5 = _week_rows(db, f"""
        SELECT coalesce(nullif(t.region,''),'(미상)') region, count(*) n, sum(coalesce(t.repair_amount_krw,0))::bigint krw
        {ship} AND EXTRACT(YEAR FROM t.action_date) = :y GROUP BY 1 ORDER BY 2 DESC
    """, {"y": year})
    c1_etc = _week_rows(db, f"""
        SELECT coalesce(nullif(t.product_model,''),'(제품명 미기재)') model, count(*) n
        {svc} AND EXTRACT(YEAR FROM t.received_date) = :y
          AND coalesce(nullif(t.product_line,''),'기타') = '기타'
        GROUP BY 1 ORDER BY 2 DESC
    """, {"y": year})

    r_base = f"FROM receivable r {_LBR} WHERE r.team_code IN ('M','D')"
    r1 = _week_rows(db, f"""
        SELECT coalesce(nullif(r.party_type,''),'(미상)') channel, coalesce(nullif(r.currency,''),'(미상)') cur,
               sum(coalesce(r.balance,0)) bal
        {r_base} GROUP BY 1, 2 ORDER BY 3 DESC
    """, {})
    r2 = _week_rows(db, f"""
        SELECT coalesce(nullif(r.status,''),'(미상)') status, coalesce(nullif(r.currency,''),'(미상)') cur,
               sum(coalesce(r.balance,0)) bal
        {r_base} GROUP BY 1, 2 ORDER BY 3 DESC
    """, {})
    r3 = _week_rows(db, f"""
        SELECT coalesce(nullif(r.country,''),'(미상)') country, coalesce(nullif(r.currency,''),'(미상)') cur,
               sum(coalesce(r.balance,0)) bal
        {r_base} GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 25
    """, {})

    return {"cards": cards,
            "w1": w1, "w2": w2, "w3": w3, "m1": m1, "m2": m2, "m3": m3,
            "c1": c1, "c1_etc": c1_etc, "c2": c2, "c3": c3, "c4": c4, "c5": c5,
            "r1": r1, "r2": r2, "r3": r3}
