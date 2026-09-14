"""사업계획(plan_item) 집계 엔드포인트 — 구글시트 '업무 세부 실행계획' 기반."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db

router = APIRouter(prefix="/api/plan", tags=["plan"])


def _latest_batch(db: Session):
    return db.execute(text("""
        SELECT pi.batch_id
          FROM plan_item pi
          JOIN v_latest_batch lb ON lb.batch_id = pi.batch_id
         ORDER BY pi.batch_id DESC
         LIMIT 1
    """)).scalar()


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    b = _latest_batch(db)
    if not b:
        return {"label": None, "items": [], "by_category": [], "by_team": [],
                "monthly": [], "totals": {}}

    label = db.execute(text("""
        SELECT p.label FROM report_period p
         JOIN plan_item pi ON pi.period_id = p.id WHERE pi.batch_id = :b LIMIT 1
    """), {"b": b}).scalar()

    items = db.execute(text("""
        SELECT category, plan_name, team_code, team_label, goal_text, goal_n,
               detail, expect, months, progress, seq
          FROM plan_item WHERE batch_id = :b ORDER BY seq
    """), {"b": b}).mappings().all()
    items = [dict(r) for r in items]

    by_category = db.execute(text("""
        SELECT category,
               count(*)                       AS tasks,
               coalesce(sum(goal_n), 0)::int  AS goal_n
          FROM plan_item WHERE batch_id = :b
         GROUP BY category ORDER BY min(seq)
    """), {"b": b}).mappings().all()

    by_team = db.execute(text("""
        SELECT coalesce(team_code, team_label, '공통') AS team,
               count(*)                      AS tasks,
               coalesce(sum(goal_n), 0)::int AS goal_n
          FROM plan_item WHERE batch_id = :b
         GROUP BY 1 ORDER BY 2 DESC
    """), {"b": b}).mappings().all()

    # 월별 계획 활동량: months JSON 에서 그 달에 내용이 있는 과제 수 (분류별)
    import json
    cats = [c["category"] for c in by_category]
    monthly = []
    for m in range(1, 13):
        row = {"month": m, "total": 0}
        for c in cats:
            row[c] = 0
        for it in items:
            try:
                mm = json.loads(it["months"] or "{}")
            except Exception:
                mm = {}
            if (mm.get(str(m)) or "").strip():
                row["total"] += 1
                if it["category"] in row:
                    row[it["category"]] += 1
        monthly.append(row)

    # 누계(계획 활동 연속 진행 여부와 무관하게, 그 달까지 '활동이 계획된 과제-월' 누적)
    cum = 0
    for row in monthly:
        cum += row["total"]
        row["cum"] = cum

    # 진행률(있으면): 과제별 최신 월 progress 평균
    prog_vals = []
    for it in items:
        try:
            pr = json.loads(it["progress"] or "{}")
        except Exception:
            pr = {}
        if pr:
            last = max(pr, key=lambda k: int(k))
            prog_vals.append(float(pr[last]))
    avg_progress = round(sum(prog_vals) / len(prog_vals) * 100, 1) if prog_vals else None

    totals = {
        "tasks": len(items),
        "goal_n": sum((c["goal_n"] or 0) for c in by_category),
        "categories": len(cats),
        "avg_progress": avg_progress,
        "has_progress": bool(prog_vals),
    }
    return {"label": label, "items": items,
            "by_category": [dict(r) for r in by_category],
            "by_team": [dict(r) for r in by_team],
            "monthly": monthly, "totals": totals}
