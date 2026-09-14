from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from .dashboard import _resolve_batch

router = APIRouter(prefix="/api/map", tags=["map"])


@router.get("/config")
def map_config():
    """프런트에 국내 상세지도 타일 설정 전달. 값이 비어있으면 프런트는 '국내 탭'을 숨긴다."""
    return {
        "kr_tile_url": settings.kr_map_tile_url,
        "kr_attribution": settings.kr_map_attribution,
        "kr_enabled": bool(settings.kr_map_tile_url),
    }


@router.get("/countries")
def countries(
    db: Session = Depends(get_db),
    period_id: int | None = None,
    ptype: str = "monthly",
    metric: str = Query("cases", enum=["cases", "open_issues", "revenue", "receivable"]),
):
    """
    세계 국가 단위 집계. 프런트는 이 값을 번들된 world GeoJSON 의 iso3 로 조인해
    ECharts choropleth / 버블맵으로 그린다. (외부 지도 API 불필요)
    """
    batch = _resolve_batch(db, period_id, ptype)
    if not batch:
        return {"metric": metric, "rows": []}

    if metric in ("cases", "open_issues"):
        cond = "AND result = '대응 중'" if metric == "open_issues" else ""
        rows = db.execute(text(f"""
            SELECT COALESCE(gp.canonical, sc.country) AS country,
                   gp.iso3, gp.lat, gp.lng, gp.region_group,
                   COUNT(*) AS value
              FROM svc_case sc
              LEFT JOIN geo_place gp ON gp.name_ko = sc.country AND gp.kind = 'country'
             WHERE sc.batch_id = :b {cond}
             GROUP BY 1, gp.iso3, gp.lat, gp.lng, gp.region_group
             ORDER BY value DESC
        """), {"b": batch}).mappings().all()
    elif metric == "receivable":
        rb = _resolve_batch(db, period_id, "weekly") or batch
        rows = db.execute(text("""
            SELECT COALESCE(gp.canonical, r.country) AS country,
                   gp.iso3, gp.lat, gp.lng, gp.region_group,
                   SUM(r.balance_krw)::bigint AS value
              FROM receivable r
              LEFT JOIN geo_place gp ON gp.name_ko = r.country AND gp.kind='country'
             WHERE r.batch_id = :b AND COALESCE(r.balance,0) <> 0
             GROUP BY 1, gp.iso3, gp.lat, gp.lng, gp.region_group
             ORDER BY value DESC
        """), {"b": rb}).mappings().all()
    else:  # revenue
        rb = _resolve_batch(db, period_id, "weekly") or batch
        rows = db.execute(text("""
            SELECT COALESCE(gp.canonical, c.country) AS country,
                   gp.iso3, gp.lat, gp.lng, gp.region_group,
                   SUM(c.amount_krw)::bigint AS value
              FROM collection_line c
              LEFT JOIN geo_place gp ON gp.name_ko = c.country AND gp.kind='country'
             WHERE c.batch_id = :b
             GROUP BY 1, gp.iso3, gp.lat, gp.lng, gp.region_group
             ORDER BY value DESC
        """), {"b": rb}).mappings().all()

    unmatched = [r["country"] for r in rows if not r["iso3"]]
    return {"metric": metric, "rows": list(rows), "unmatched_countries": unmatched}


@router.get("/kr-sites")
def kr_sites(db: Session = Depends(get_db), period_id: int | None = None):
    """
    국내 방문 AS 위치(핀). K테크 서비스 이력의 '지역'(시·군) → geo_place(kind='kr_city') 좌표.
    kr_tile_url 이 설정돼 있어야 프런트에서 이 탭이 보인다.
    """
    batch = _resolve_batch(db, period_id, "weekly")
    if not batch:
        return {"sites": []}
    rows = db.execute(text("""
        SELECT sc.region AS city, gp.lat, gp.lng,
               COUNT(*) AS visits,
               array_agg(DISTINCT sc.product_model) AS models
          FROM svc_case sc
          JOIN geo_place gp ON gp.name_ko = sc.region AND gp.kind = 'kr_city'
         WHERE sc.batch_id = :b AND gp.lat IS NOT NULL
         GROUP BY sc.region, gp.lat, gp.lng
         ORDER BY visits DESC
    """), {"b": batch}).mappings().all()
    return {"sites": list(rows)}
