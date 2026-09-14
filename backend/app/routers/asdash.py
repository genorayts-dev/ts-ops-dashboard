"""AS 접수처리대장(as_ticket) 집계 엔드포인트."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db

router = APIRouter(prefix="/api/as", tags=["as"])

# 항상 최신 batch(scope_key 별) 만 본다
_LB = "JOIN v_latest_batch lb ON lb.batch_id = t.batch_id"
# 부산지사는 K Tech 조직에 통합해서 집계한다 (원본 org 는 t.org 로 별도 유지)
_ORG = "(CASE WHEN t.org = '부산' THEN 'K' ELSE t.org END)"
# '서비스 건수' 로 인정하는 행 — 「AS 매출 해외」(해외 발송) 탭 유래는 건수에서 제외.
# (금액·지도(국가별)에는 계속 포함 — 매출/거래 데이터이므로.)
_SVC = "t.src IS DISTINCT FROM 'overseas_ship'"


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    total = db.execute(text(f"SELECT count(*) FROM as_ticket t {_LB} WHERE {_SVC}")).scalar()
    # 팀(org) 단위로만 집계. 장비군(product_line)은 소스마다 채워짐이 달라 분리하지 않음
    # (장비 세부는 '장비 모델 TOP 20' 참고).
    # n/paid_n = 서비스 건수(해외발송 제외), krw = 수리비(해외발송 포함).
    by_line = db.execute(text(f"""
        SELECT {_ORG} org, NULL AS product_line,
               count(*) FILTER (WHERE {_SVC}) n,
               sum((warranty='유상')::int) FILTER (WHERE {_SVC}) paid_n,
               sum(coalesce(repair_amount_krw,0))::bigint krw
        FROM as_ticket t {_LB}
        GROUP BY 1 ORDER BY 1
    """)).mappings().all()
    warranty = db.execute(text(f"""
        SELECT coalesce(warranty,'(미상)') k, count(*) n
        FROM as_ticket t {_LB} WHERE {_SVC} GROUP BY 1 ORDER BY n DESC
    """)).mappings().all()
    fix_class = db.execute(text(f"""
        SELECT coalesce(fix_class,'(미상)') k, count(*) n
        FROM as_ticket t {_LB} WHERE {_SVC} GROUP BY 1 ORDER BY n DESC
    """)).mappings().all()
    result = db.execute(text(f"""
        SELECT coalesce(result,'(미상)') k, count(*) n
        FROM as_ticket t {_LB} WHERE {_SVC} GROUP BY 1 ORDER BY n DESC
    """)).mappings().all()
    return {
        "total": total,
        "by_line": list(by_line),
        "warranty": list(warranty),
        "fix_class": list(fix_class),
        "result": list(result),
    }


@router.get("/monthly")
def monthly(db: Session = Depends(get_db), year: int = 2026):
    # 건수/수리비 모두 데이터시트 '조치일(완료일)' 기준으로 월별 분할 (해당 연도만).
    # 월간보고 매출(청구월) 과 시점을 맞추기 위해 접수일 대신 조치일 사용.
    rows = db.execute(text(f"""
        SELECT EXTRACT(MONTH FROM t.action_date)::int AS month,
               {_ORG} AS org,
               count(*) FILTER (WHERE {_SVC}) n,
               sum(coalesce(t.repair_amount_krw,0))::bigint krw
        FROM as_ticket t {_LB}
        WHERE t.action_date >= make_date(:y,1,1) AND t.action_date < make_date(:y+1,1,1)
        GROUP BY 1, 2 ORDER BY 1, 2
    """), {"y": year}).mappings().all()
    return list(rows)


_FX = "CASE upper(coalesce({c},'')) WHEN 'USD' THEN 1380 WHEN 'EUR' THEN 1640 " \
      "WHEN 'JPY' THEN 9.4 WHEN 'CNY' THEN 195 ELSE 1 END"


@router.get("/countries")
def countries(db: Session = Depends(get_db)):
    """
    해외 AS: 건수(n)는 as_ticket(구글시트 건별) 기준.
    거래규모(recv_krw)는 매출채권(receivable, 구글시트 채권 탭) 청구금액을 국가별로 합산 (원화 환산).
    """
    clean = (r"btrim(regexp_replace("
             r"regexp_replace({c}, '\s*\(.*$', ''), "
             r"'\s+[A-Za-z][A-Za-z0-9]*\s*$', ''))")
    rows = db.execute(text(f"""
        WITH tix AS (
            SELECT coalesce(g.canonical, {clean.format(c='t.country')}) country,
                   max(g.iso3) iso3, max(g.lat) lat, max(g.lng) lng, max(g.region_group) region_group,
                   count(*) n
            FROM as_ticket t {_LB}
            LEFT JOIN geo_place g
              ON lower(g.name_ko) = lower({clean.format(c='t.country')}) AND g.kind='country'
            WHERE t.is_overseas AND coalesce(t.country,'') <> ''
            GROUP BY 1
        ),
        rcv AS (
            SELECT coalesce(g.canonical, {clean.format(c='r.country')}) country,
                   sum(coalesce(r.amount,0) * {_FX.format(c='r.currency')})::bigint krw,
                   sum(coalesce(r.balance,0) * {_FX.format(c='r.currency')})::bigint bal_krw
            FROM receivable r {_LB.replace('t.batch_id','r.batch_id')}
            LEFT JOIN geo_place g ON lower(g.name_ko) = lower({clean.format(c='r.country')}) AND g.kind='country'
            WHERE coalesce(r.country,'') <> ''
            GROUP BY 1
        )
        SELECT coalesce(tix.country, rcv.country) country,
               tix.iso3, tix.lat, tix.lng, tix.region_group,
               coalesce(tix.n, 0) n,
               coalesce(rcv.krw, 0) revenue_krw,
               coalesce(rcv.bal_krw, 0) balance_krw
        FROM tix FULL OUTER JOIN rcv ON rcv.country = tix.country
        ORDER BY n DESC, revenue_krw DESC
    """)).mappings().all()
    return {"rows": list(rows),
            "unmatched": sorted({r["country"] for r in rows if not r["iso3"] and r["n"]})}


@router.get("/by-model")
def by_model(db: Session = Depends(get_db), limit: int = 25):
    rows = db.execute(text(f"""
        SELECT product_model,
               count(*) n,
               sum((warranty='유상')::int) paid_n,
               sum(coalesce(repair_amount_krw,0))::bigint krw
        FROM as_ticket t {_LB}
        WHERE coalesce(product_model,'') <> '' AND {_SVC}
        GROUP BY product_model ORDER BY n DESC LIMIT :lim
    """), {"lim": limit}).mappings().all()
    return list(rows)


@router.get("/repeat")
def repeat_offenders(db: Session = Depends(get_db), min_count: int = 3, limit: int = 30):
    rows = db.execute(text(f"""
        SELECT serial_no, max(product_model) model, max({_ORG}) org,
               count(*) n, max(shipped_to) last_site
        FROM as_ticket t {_LB}
        WHERE coalesce(serial_no,'') <> '' AND {_SVC}
        GROUP BY serial_no HAVING count(*) >= :mc
        ORDER BY n DESC LIMIT :lim
    """), {"mc": min_count, "lim": limit}).mappings().all()
    return list(rows)


@router.get("/filters")
def filters(db: Session = Depends(get_db)):
    """AS 내역 조회 필터 옵션 (org 통합 / product_line / month)."""
    orgs = db.execute(text(f"SELECT DISTINCT {_ORG} FROM as_ticket t {_LB} WHERE {_SVC} ORDER BY 1")).scalars().all()
    lines = db.execute(text(f"SELECT DISTINCT product_line FROM as_ticket t {_LB} "
                            f"WHERE product_line IS NOT NULL AND {_SVC} ORDER BY product_line")).scalars().all()
    months = db.execute(text(f"""
        SELECT DISTINCT EXTRACT(MONTH FROM t.action_date)::int AS m
        FROM as_ticket t {_LB}
        WHERE {_SVC} AND t.action_date >= make_date(2026,1,1) AND t.action_date < make_date(2027,1,1)
        ORDER BY 1""")).scalars().all()
    return {"orgs": list(orgs), "product_lines": list(lines), "months": list(months)}


@router.get("/tickets")
def tickets(db: Session = Depends(get_db), org: str | None = None,
            product_line: str | None = None, country: str | None = None,
            month: int | None = None, result: str | None = None, warranty: str | None = None,
            q: str | None = None, limit: int = 500, offset: int = 0):
    limit = min(limit, 5000)
    where = [_SVC]  # AS 내역 = 서비스 건 (해외 발송 탭 제외)
    p: dict = {"lim": limit, "off": offset}
    if org:  # 통합 org 기준 필터 (부산 → K 포함)
        where.append(f"{_ORG} = :org"); p["org"] = org
    if product_line:
        where.append("t.product_line = :pl"); p["pl"] = product_line
    if country:
        where.append("t.country = :c"); p["c"] = country
    if month:
        where.append("EXTRACT(MONTH FROM t.action_date) = :mo "
                     "AND EXTRACT(YEAR FROM t.action_date) = 2026")
        p["mo"] = month
    if result:
        where.append("t.result = :res"); p["res"] = result
    if warranty:
        where.append("t.warranty = :war"); p["war"] = warranty
    if q:
        where.append("(t.symptom ILIKE :q OR t.action ILIKE :q OR t.cause ILIKE :q "
                     "OR t.shipped_to ILIKE :q OR t.product_model ILIKE :q OR t.serial_no ILIKE :q)")
        p["q"] = f"%{q}%"
    ws = " AND ".join(where)
    total = db.execute(text(f"SELECT count(*) FROM as_ticket t {_LB} WHERE {ws}"), p).scalar()
    rows = db.execute(text(f"""
        SELECT {_ORG} org, t.org raw_org, t.product_line, t.shipped_to, t.country, t.region_kr,
               t.product_model, t.serial_no, t.warranty, t.received_date, t.action_date, t.result,
               t.repair_currency, t.repair_amount, t.symptom, t.action, t.cause, t.fix_class
        FROM as_ticket t {_LB}
        WHERE {ws}
        ORDER BY t.action_date DESC NULLS LAST, t.received_date DESC NULLS LAST
        LIMIT :lim OFFSET :off
    """), p).mappings().all()
    return {"total": total, "returned": len(rows), "rows": list(rows)}


@router.get("/kr-regions")
def kr_regions(db: Session = Depends(get_db)):
    """국내 AS 시·도별 집계 (지도 탭 ②). 부산지사도 K Tech 로 통합."""
    rows = db.execute(text(f"""
        SELECT coalesce(region_kr,'(미상)') region, {_ORG} org,
               count(*) n, sum(coalesce(repair_amount_krw,0))::bigint krw
        FROM as_ticket t {_LB}
        WHERE NOT is_overseas
        GROUP BY 1, 2 ORDER BY n DESC
    """)).mappings().all()
    filled = db.execute(text(f"SELECT count(*) FROM as_ticket t {_LB} "
                             f"WHERE NOT is_overseas AND region_kr IS NOT NULL")).scalar()
    total = db.execute(text(f"SELECT count(*) FROM as_ticket t {_LB} WHERE NOT is_overseas")).scalar()
    return {"rows": list(rows), "filled": filled, "domestic_total": total}
