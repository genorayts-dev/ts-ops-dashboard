"""매출채권(receivable) 집계 — 구글시트 'AS 채권 D/M/K' 탭 기반."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db

router = APIRouter(prefix="/api/recv", tags=["recv"])

_LB = "JOIN v_latest_batch lb ON lb.batch_id = r.batch_id"
# 사업계획(연간) 고정환율 → 원화 환산
_FX = ("CASE upper(coalesce(r.currency,'')) "
       "WHEN 'USD' THEN 1380 WHEN 'EUR' THEN 1640 WHEN 'JPY' THEN 9.4 "
       "WHEN 'CNY' THEN 195 ELSE 1 END")
_BALK = f"(coalesce(r.balance,0) * {_FX})"
_AMTK = f"(coalesce(r.amount,0) * {_FX})"
# 미회수 상태 (연체/미회수/장기미수)
_OPEN = "(r.is_new OR r.status IN ('연체','미회수','장기미수'))"
_LONG = "(r.status = '장기미수')"
_AGE = "(CURRENT_DATE - coalesce(r.due_date, r.ship_date))"


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    card = db.execute(text(f"""
        SELECT sum({_AMTK})::bigint billed_krw,
               sum({_BALK})::bigint bal_krw,
               sum({_BALK}) FILTER (WHERE {_OPEN})::bigint overdue_krw,
               sum({_BALK}) FILTER (WHERE {_LONG})::bigint long_krw,
               count(*) FILTER (WHERE coalesce(r.balance,0) > 0) open_n,
               count(DISTINCT r.entity) entities
        FROM receivable r {_LB}
    """)).mappings().one()

    by_team = db.execute(text(f"""
        SELECT r.team_code team,
               count(*) FILTER (WHERE coalesce(r.balance,0) > 0) n,
               sum({_BALK})::bigint bal_krw,
               sum({_BALK}) FILTER (WHERE {_OPEN})::bigint overdue_krw,
               sum({_BALK}) FILTER (WHERE {_LONG})::bigint long_krw
        FROM receivable r {_LB}
        GROUP BY 1 ORDER BY 3 DESC NULLS LAST
    """)).mappings().all()

    by_channel = db.execute(text(f"""
        SELECT coalesce(r.party_type,'(미상)') k,
               count(*) n, sum({_BALK})::bigint bal_krw
        FROM receivable r {_LB}
        WHERE coalesce(r.balance,0) <> 0
        GROUP BY 1 ORDER BY 3 DESC NULLS LAST
    """)).mappings().all()

    by_currency = db.execute(text(f"""
        SELECT coalesce(r.currency,'(미상)') k,
               count(*) FILTER (WHERE coalesce(r.balance,0) > 0) n,
               sum(coalesce(r.balance,0))::bigint bal,
               sum({_BALK})::bigint bal_krw
        FROM receivable r {_LB}
        GROUP BY 1 ORDER BY 4 DESC NULLS LAST
    """)).mappings().all()

    by_status = db.execute(text(f"""
        SELECT coalesce(r.status, CASE WHEN r.is_new THEN '연체'
                                       WHEN coalesce(r.balance,0) <= 0 THEN '완납'
                                       ELSE '정상' END) k,
               count(*) n, sum({_BALK})::bigint bal_krw
        FROM receivable r {_LB}
        GROUP BY 1 ORDER BY 3 DESC NULLS LAST
    """)).mappings().all()

    aging = db.execute(text(f"""
        SELECT CASE
                 WHEN {_AGE} IS NULL THEN '미정'
                 WHEN {_AGE} <= 30 THEN '0-30'
                 WHEN {_AGE} <= 60 THEN '31-60'
                 WHEN {_AGE} <= 90 THEN '61-90'
                 WHEN {_AGE} <= 180 THEN '91-180'
                 ELSE '180+' END bucket,
               count(*) n, sum({_BALK})::bigint bal_krw
        FROM receivable r {_LB}
        WHERE coalesce(r.balance,0) > 0
        GROUP BY 1
    """)).mappings().all()
    order = ['0-30', '31-60', '61-90', '91-180', '180+', '미정']
    aging = sorted(aging, key=lambda x: order.index(x['bucket']) if x['bucket'] in order else 99)

    top = db.execute(text(f"""
        WITH g AS (
          SELECT r.entity, r.team_code team, max(r.party_type) channel,
                 max(r.country) country, max(r.currency) currency,
                 count(*) n,
                 sum(coalesce(r.balance,0))::bigint bal,
                 sum({_BALK})::bigint bal_krw,
                 bool_or({_OPEN}) overdue,
                 bool_or({_LONG}) long_overdue
          FROM receivable r {_LB}
          WHERE coalesce(r.entity,'') <> '' AND coalesce(r.balance,0) > 0
          GROUP BY r.entity, r.team_code
        ), ranked AS (
          SELECT *, row_number() OVER (PARTITION BY team ORDER BY bal_krw DESC) rn
          FROM g
        )
        SELECT entity, team, channel, country, currency, n, bal, bal_krw, overdue, long_overdue
        FROM ranked WHERE rn <= 15
        ORDER BY team, bal_krw DESC
    """)).mappings().all()

    return {
        "cards": dict(card),
        "by_team": [dict(x) for x in by_team],
        "by_channel": [dict(x) for x in by_channel],
        "by_currency": [dict(x) for x in by_currency],
        "by_status": [dict(x) for x in by_status],
        "aging": [dict(x) for x in aging],
        "top": [dict(x) for x in top],
    }
