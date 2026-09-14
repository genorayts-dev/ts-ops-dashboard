"""?꾩옱 ?곗씠?곕? ?꾩쟾???낅┰???ㅽ봽?쇱씤 HTML ?ㅻ깄?룹쑝濡??대낫?대뒗 ?붾뱶?ъ씤??"""
import datetime
import json
import os

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..db import get_db
from .asdash import (
    overview as as_overview,
    monthly as as_monthly,
    by_model as as_bymodel,
    repeat_offenders as as_repeat,
    countries as as_countries,
    kr_regions as as_krregions,
    filters as as_filters,
    tickets as as_tickets,
)
from .dashboard import trend as dashboard_trend
from .recv import overview as recv_overview

router = APIRouter(prefix="/api/export", tags=["export"])

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
_TEMPLATE_PATH = os.path.join(_STATIC_DIR, "snapshot_template.html")
_VENDOR_DIR = "/vendor"


def _safe(s: str) -> str:
    # ?꾨쿋?쒕맂 JSON/JS ?덉뿉 "</script"媛 臾몄옄 洹몃?濡??덉쑝硫?HTML ?뚯꽌媛 ?ㅽ겕由쏀듃瑜?    # 議곌린 醫낅즺?쒗궎誘濡? ?щ옒???욎뿉 諛깆뒳?섏떆瑜??ｌ뼱 ?댁뒪耳?댄봽?쒕떎.
    return s.replace("</script", "<\\/script")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


@router.get("/snapshot", response_class=HTMLResponse)
def export_snapshot(db: Session = Depends(get_db)):
    year = datetime.date.today().year

    data = {
        "as_overview": as_overview(db=db),
        "trend_revenue": dashboard_trend(db=db, metric="revenue_krw", team="all", year=year),
        "trend_service": dashboard_trend(db=db, metric="service_cnt", team="all", year=year),
        "trend_inbound": dashboard_trend(db=db, metric="inbound_cnt", team="all", year=year),
        "as_monthly": as_monthly(db=db, year=year),
        "as_bymodel": as_bymodel(db=db, limit=10),
        "as_repeat": as_repeat(db=db, min_count=3, limit=50),
        "as_countries": as_countries(db=db),
        "as_krregions": as_krregions(db=db),
        "as_filters": as_filters(db=db),
        "as_tickets": as_tickets(db=db, limit=200000),
        "recv_overview": recv_overview(db=db),
    }
    payload = jsonable_encoder(data)
    snapshot_json = _safe(json.dumps(payload, ensure_ascii=False))

    echarts_js = _safe(_read(os.path.join(_VENDOR_DIR, "echarts.min.js")))
    world_json = _safe(_read(os.path.join(_VENDOR_DIR, "world.json")))
    korea_json = _safe(_read(os.path.join(_VENDOR_DIR, "korea.json")))

    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    html = _read(_TEMPLATE_PATH)
    html = html.replace("/*__ECHARTS_JS__*/", echarts_js)
    html = html.replace("/*__WORLD_JSON__*/", world_json)
    html = html.replace("/*__KOREA_JSON__*/", korea_json)
    html = html.replace("/*__SNAPSHOT_JSON__*/", snapshot_json)
    html = html.replace("__GENERATED_AT__", generated_at)

    filename = f"ts-dashboard-snapshot-{datetime.date.today().isoformat()}.html"
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
