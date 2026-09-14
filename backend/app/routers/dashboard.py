from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/periods")
def periods(db: Session = Depends(get_db), ptype: str = Query("weekly")):
    rows = db.execute(text("""
        SELECT p.id, p.label, p.ptype, p.year, p.month, p.week_no, p.date_start, p.date_end,
               lb.batch_id, lb.uploaded_at
          FROM report_period p
          JOIN v_latest_batch lb ON lb.period_id = p.id
         WHERE p.ptype = :ptype
         ORDER BY p.year DESC, p.month DESC NULLS LAST, p.week_no DESC NULLS LAST
    """), {"ptype": ptype}).mappings().all()
    return list(rows)


def _resolve_batch(db: Session, period_id: int | None, ptype: str) -> int | None:
    if period_id:
        r = db.execute(text(
            "SELECT batch_id FROM v_latest_batch WHERE period_id=:p ORDER BY uploaded_at DESC LIMIT 1"
        ), {"p": period_id}).scalar()
        return r
    return db.execute(text("""
        SELECT lb.batch_id FROM v_latest_batch lb JOIN report_period p ON p.id=lb.period_id
        WHERE p.ptype=:t ORDER BY p.year DESC, p.month DESC NULLS LAST, p.week_no DESC NULLS LAST
        LIMIT 1
    """), {"t": ptype}).scalar()


@router.get("/overview")
def overview(db: Session = Depends(get_db), period_id: int | None = None, ptype: str = "weekly"):
    batch = _resolve_batch(db, period_id, ptype)
    if not batch:
        return {"batch_id": None, "teams": [], "total": {}}
    teams = db.execute(text("""
        SELECT team_code, received, completed, completion_rate, inbound,
               revenue_krw, revenue_krw_ytd
          FROM svc_summary WHERE batch_id = :b ORDER BY team_code
    """), {"b": batch}).mappings().all()
    total = {
        "received": sum((t["received"] or 0) for t in teams),
        "inbound": sum((t["inbound"] or 0) for t in teams),
        "revenue_krw": sum((t["revenue_krw"] or 0) for t in teams),
        "revenue_krw_ytd": sum((t["revenue_krw_ytd"] or 0) for t in teams),
    }
    return {"batch_id": batch, "teams": list(teams), "total": total}


def _latest_monthly_batch(db: Session, year: int):
    return db.execute(text("""
        SELECT mt.batch_id
          FROM monthly_trend mt
          JOIN v_latest_batch lb ON lb.batch_id = mt.batch_id
          JOIN report_period p ON p.id = mt.period_id
         WHERE mt.year = :y
         ORDER BY p.year DESC, p.month DESC NULLS LAST
         LIMIT 1
    """), {"y": year}).scalar()


@router.get("/monthly-months")
def monthly_months(db: Session = Depends(get_db), year: int = 2026):
    """월간보고가 적재되어 조회 가능한 월 목록."""
    b = _latest_monthly_batch(db, year)
    if not b:
        return {"batch_id": None, "months": []}
    months = db.execute(text("""
        SELECT DISTINCT month FROM monthly_trend WHERE batch_id = :b ORDER BY month
    """), {"b": b}).scalars().all()
    return {"batch_id": b, "months": list(months)}


@router.get("/monthly")
def monthly(db: Session = Depends(get_db), month: int | None = None, year: int = 2026):
    """선택 월의 팀별 실적 (월간보고 표지 매트릭스 기준). month 미지정 시 최신 월."""
    b = _latest_monthly_batch(db, year)
    if not b:
        return {"month": None, "teams": [], "total": {}}
    if month is None:
        month = db.execute(text("SELECT max(month) FROM monthly_trend WHERE batch_id=:b"),
                           {"b": b}).scalar()
    rows = db.execute(text("""
        SELECT team_code, service_cnt, inbound_cnt, revenue_krw
          FROM monthly_trend WHERE batch_id = :b AND month = :m ORDER BY team_code
    """), {"b": b, "m": month}).mappings().all()
    total = {
        "service_cnt": sum((r["service_cnt"] or 0) for r in rows),
        "inbound_cnt": sum((r["inbound_cnt"] or 0) for r in rows),
        "revenue_krw": sum((r["revenue_krw"] or 0) for r in rows),
    }
    # 누계(연초~선택월)
    ytd = db.execute(text("""
        SELECT SUM(revenue_krw)::bigint FROM monthly_trend
         WHERE batch_id = :b AND month <= :m
    """), {"b": b, "m": month}).scalar()
    return {"month": month, "teams": list(rows), "total": total, "revenue_krw_ytd": ytd}


@router.get("/trend")
def trend(db: Session = Depends(get_db), metric: str = "revenue_krw",
          team: str = "all", year: int = 2026):
    allowed = {"service_cnt", "inbound_cnt", "revenue_krw"}
    if metric not in allowed:
        metric = "revenue_krw"
    # 월간 실적 파일은 각자 연초~해당월 매트릭스를 통째로 담는다.
    # → 여러 월간 파일을 올리면 v_latest_batch 에 다 잡히므로, 가장 최근 월(period)의
    #   monthly_trend batch 하나만 사용한다.
    batch = db.execute(text("""
        SELECT mt.batch_id
          FROM monthly_trend mt
          JOIN v_latest_batch lb ON lb.batch_id = mt.batch_id
          JOIN report_period p ON p.id = mt.period_id
         WHERE mt.year = :y
         ORDER BY p.year DESC, p.month DESC NULLS LAST
         LIMIT 1
    """), {"y": year}).scalar()
    if not batch:
        return []
    team_filter = "" if team == "all" else "AND team_code = :team"
    rows = db.execute(text(f"""
        SELECT month, team_code, {metric}::bigint AS value
          FROM monthly_trend
         WHERE batch_id = :b AND year = :y {team_filter}
         ORDER BY month, team_code
    """), {"b": batch, "y": year, "team": team}).mappings().all()

    # AS매출: D테크만 월간보고, M/K테크는 데이터 통합시트(as_ticket 조치일 기준 수리비 합)로 대체.
    #   추가로 K테크는 유지보수(월납) 계약액을 월별로 가산한다(월간보고엔 있으나 통합시트엔 없음).
    #   (사용자 지시 2026-09-10. 건수/Inbound 는 그대로 월간보고 유지.)
    if metric == "revenue_krw":
        sheet = db.execute(text("""
            SELECT EXTRACT(MONTH FROM t.action_date)::int AS month,
                   (CASE WHEN t.org = '부산' THEN 'K' ELSE t.org END) AS team_code,
                   sum(coalesce(t.repair_amount_krw, 0))::bigint AS value
              FROM as_ticket t
              JOIN v_latest_batch lb ON lb.batch_id = t.batch_id
             WHERE t.action_date >= make_date(:y, 1, 1)
               AND t.action_date <  make_date(:y + 1, 1, 1)
             GROUP BY 1, 2
        """), {"y": year}).mappings().all()
        sheet_mk = {(r["month"], r["team_code"]): r["value"]
                    for r in sheet if r["team_code"] in ("M", "K")}

        # K 유지보수 월납: 계약이 해당 월에 유효(계약월<=당월 & 만료일>=당월초)하면 가산.
        #   통합시트 'AS 유지보수 K' 탭 → maintenance_contract. v_latest_batch 로 최신
        #   동기화분만 집계 → 재동기화해도 이전 batch 와 중복되지 않음.
        maint = db.execute(text("""
            SELECT g.mo AS month,
                   sum(mc.monthly_fee * CASE upper(coalesce(mc.currency,'KRW'))
                       WHEN 'USD' THEN 1380 WHEN 'EUR' THEN 1640 WHEN 'JPY' THEN 9.4
                       WHEN 'CNY' THEN 195 ELSE 1 END)::bigint AS fee
              FROM generate_series(1, 12) AS g(mo)
              JOIN maintenance_contract mc
                ON mc.active AND mc.team_code = 'K'
               AND mc.contract_on <= (make_date(:y, g.mo, 1) + INTERVAL '1 month - 1 day')
               AND (mc.expires_on IS NULL OR mc.expires_on >= make_date(:y, g.mo, 1))
              JOIN v_latest_batch lb ON lb.batch_id = mc.batch_id
             GROUP BY g.mo
        """), {"y": year}).mappings().all()
        maint_by_month = {r["month"]: int(r["fee"] or 0) for r in maint}

        want = {"M", "K"} if team == "all" else ({team} & {"M", "K"})
        merged = [dict(r) for r in rows if r["team_code"] not in ("M", "K")]
        months = {r["month"] for r in rows} | {m for (m, _) in sheet_mk}
        for mth in months:
            for tc in want:
                v = int(sheet_mk.get((mth, tc), 0))
                if tc == "K":
                    v += maint_by_month.get(mth, 0)
                merged.append({"month": mth, "team_code": tc, "value": v})
        merged.sort(key=lambda r: (r["month"] or 0, r["team_code"]))
        return merged

    return list(rows)


@router.get("/defects")
def defects(db: Session = Depends(get_db), period_id: int | None = None,
            ptype: str = "weekly", team: str | None = None):
    batch = _resolve_batch(db, period_id, ptype)
    tf = "AND team_code = :team" if team else ""
    rows = db.execute(text(f"""
        SELECT team_code, category, subtype, cnt_period, cnt_ytd
          FROM defect_breakdown WHERE batch_id = :b {tf}
         ORDER BY category, cnt_period DESC NULLS LAST
    """), {"b": batch, "team": team}).mappings().all()
    return list(rows)


@router.get("/equipment")
def equipment(db: Session = Depends(get_db), period_id: int | None = None, ptype: str = "weekly"):
    batch = _resolve_batch(db, period_id, ptype)
    rows = db.execute(text("""
        SELECT team_code, product_group, model,
               SUM(visit_cnt) AS visit_cnt, SUM(shipment_cnt) AS shipment_cnt
          FROM equipment_stat WHERE batch_id = :b
         GROUP BY team_code, product_group, model
         ORDER BY visit_cnt DESC NULLS LAST
    """), {"b": batch}).mappings().all()
    return list(rows)


@router.get("/receivables")
def receivables(db: Session = Depends(get_db), period_id: int | None = None, ptype: str = "weekly"):
    batch = _resolve_batch(db, period_id, ptype)
    rows = db.execute(text("""
        SELECT party_type, entity, country, currency, amount, paid_amount, balance,
               balance_krw, ship_date, due_date, is_new, note,
               (CURRENT_DATE - due_date) AS aging_days
          FROM receivable WHERE batch_id = :b AND COALESCE(balance,0) <> 0
         ORDER BY balance_krw DESC NULLS LAST
    """), {"b": batch}).mappings().all()
    buckets = {"0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
    for r in rows:
        d = r["aging_days"] or 0
        key = "0-30" if d <= 30 else "31-60" if d <= 60 else "61-90" if d <= 90 else "90+"
        buckets[key] += float(r["balance_krw"] or 0)
    return {"lines": list(rows), "aging_krw": buckets}


@router.get("/kpi")
def kpi(db: Session = Depends(get_db), period_id: int | None = None):
    """월간 KPI(실적 상세) — 항목 리스트 + 진행률 집계 + 월별 추이."""
    batch = db.execute(text("""
        SELECT k.batch_id FROM kpi_item k
        JOIN v_latest_batch lb ON lb.batch_id = k.batch_id
        JOIN report_period p ON p.id = k.period_id
        WHERE (CAST(:pid AS bigint) IS NULL OR p.id = :pid)
        ORDER BY p.year DESC, p.month DESC NULLS LAST
        LIMIT 1
    """), {"pid": period_id}).scalar()
    if not batch:
        return {"period_label": None, "items": [], "overall": None,
                "by_category": [], "by_team": [], "trend": []}

    label = db.execute(text("""
        SELECT p.label FROM report_period p JOIN kpi_item k ON k.period_id = p.id
        WHERE k.batch_id = :b LIMIT 1
    """), {"b": batch}).scalar()

    items = db.execute(text("""
        SELECT category, team_code, goal_text, result_text, achieved
          FROM kpi_item WHERE batch_id = :b AND is_plan = FALSE
         ORDER BY category, team_code NULLS FIRST, id
    """), {"b": batch}).mappings().all()

    plan = db.execute(text("""
        SELECT category, team_code, goal_text, plan_month
          FROM kpi_item WHERE batch_id = :b AND is_plan = TRUE
         ORDER BY category, team_code NULLS FIRST, id
    """), {"b": batch}).mappings().all()

    by_category = db.execute(text("""
        SELECT category,
               count(*) total,
               sum(CASE WHEN achieved >= 1 THEN 1 ELSE 0 END) done,
               round(avg(LEAST(achieved,1))*100, 1) pct
          FROM kpi_item WHERE batch_id = :b AND is_plan = FALSE
         GROUP BY category ORDER BY category
    """), {"b": batch}).mappings().all()

    by_team = db.execute(text("""
        SELECT COALESCE(team_code,'공통') team,
               count(*) total,
               sum(CASE WHEN achieved >= 1 THEN 1 ELSE 0 END) done,
               round(avg(LEAST(achieved,1))*100, 1) pct
          FROM kpi_item WHERE batch_id = :b AND is_plan = FALSE
         GROUP BY 1 ORDER BY 1
    """), {"b": batch}).mappings().all()

    tot = sum(c["total"] for c in by_category)
    done = sum(c["done"] for c in by_category)
    overall = {"total": tot, "done": done,
               "pct": round(done * 100 / tot, 1) if tot else 0}

    trend = db.execute(text("""
        WITH m AS (
          SELECT p.month,
                 count(*) total,
                 sum(CASE WHEN k.achieved >= 1 THEN 1 ELSE 0 END) done,
                 round(avg(LEAST(k.achieved,1))*100, 1) pct
            FROM kpi_item k
            JOIN v_latest_batch lb ON lb.batch_id = k.batch_id
            JOIN report_period p ON p.id = k.period_id
           WHERE k.is_plan = FALSE AND p.month IS NOT NULL
           GROUP BY p.month
        )
        SELECT month, total, done, pct,
               sum(total) OVER (ORDER BY month) AS cum_total,
               sum(done)  OVER (ORDER BY month) AS cum_done,
               round(sum(done) OVER (ORDER BY month) * 100.0
                     / NULLIF(sum(total) OVER (ORDER BY month), 0), 1) AS cum_pct
          FROM m ORDER BY month
    """)).mappings().all()

    plan_month = plan[0]["plan_month"] if plan else None
    return {"period_label": label, "items": list(items), "overall": overall,
            "by_category": list(by_category), "by_team": list(by_team), "trend": list(trend),
            "plan": {"month": plan_month, "count": len(plan), "items": list(plan)}}


@router.get("/issues")
def issues(db: Session = Depends(get_db), period_id: int | None = None, ptype: str = "monthly"):
    batch = _resolve_batch(db, period_id, ptype)
    rows = db.execute(text("""
        SELECT id, team_code, kind, title, occurrence, cause, action, ref_url
          FROM svc_issue WHERE batch_id = :b ORDER BY kind, id
    """), {"b": batch}).mappings().all()
    return list(rows)


@router.get("/cases")
def cases(db: Session = Depends(get_db), period_id: int | None = None,
          country: str | None = None, result: str | None = None,
          q: str | None = None, limit: int = 200, offset: int = 0):
    batch = _resolve_batch(db, period_id, "monthly")
    where = ["batch_id = :b"]
    params: dict = {"b": batch, "limit": limit, "offset": offset}
    if country:
        where.append("country = :country"); params["country"] = country
    if result:
        where.append("result = :result"); params["result"] = result
    if q:
        where.append("(title ILIKE :q OR action ILIKE :q OR product_model ILIKE :q)")
        params["q"] = f"%{q}%"
    sql = f"""
        SELECT id, team_code, region, country, product_model, product_code,
               received_date, action_date, title, action, defect_cause, result
          FROM svc_case WHERE {' AND '.join(where)}
         ORDER BY received_date DESC NULLS LAST
         LIMIT :limit OFFSET :offset
    """
    rows = db.execute(text(sql), params).mappings().all()
    return list(rows)
