"""현재 데이터를 완전히 독립된 오프라인 HTML 스냅샷으로 내보내는 엔드포인트."""
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
    # 임베드된 JSON/JS 안에 "</script"가 문자 그대로 있으면 HTML 파서가 스크립트를
    # 조기 종료시키므로, 슬래시 앞에 백슬래시를 넣어 이스케이프한다.
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
