from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import geno_one
from ..auth import current_user
from ..db import get_db
from ..ingest.geno_one_aspart import parse_geno_one_aspart
from ..ingest.geno_one_reconcile import MD_AS_HEADERS, apply as reconcile_apply_impl, find_candidates, to_md_as_row
from ..ingest.persist import persist

router = APIRouter(prefix="/api/geno_one", tags=["geno_one"])


@router.get("/status")
def status(db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT b.id AS batch_id, b.source_name, b.uploaded_at, b.status, b.warnings,
               (SELECT count(*) FROM geno_one_ticket t WHERE t.batch_id = b.id) AS n
          FROM upload_batch b
         WHERE b.scope_key = 'geno_one_aspart'
         ORDER BY b.uploaded_at DESC LIMIT 1
    """)).mappings().first()
    return {"enabled": geno_one.enabled(), "last_sync": dict(row) if row else None}


@router.post("/sync")
def sync(db: Session = Depends(get_db), user: str = Depends(current_user)):
    if not geno_one.enabled():
        raise HTTPException(501, "geno-one 계정이 설정되지 않았습니다 (TSD_GENO_ONE_USERNAME/PASSWORD).")
    try:
        raw = geno_one.fetch_aspart_xlsx()
    except Exception as e:
        raise HTTPException(502, f"geno-one 접속 실패: {type(e).__name__}: {e}")
    parsed = parse_geno_one_aspart(raw, "geno_one_aspart.xlsx")
    res = persist(db, parsed, filename="geno_one_aspart.xlsx", raw=raw, user=f"geno_one:{user}")
    return res


@router.get("/reconcile")
def reconcile(only_closed: bool = True, db: Session = Depends(get_db)):
    """geno_one_ticket 중 통합시트(as_ticket)에 없는 후보 미리보기(쓰기 없음)."""
    candidates = find_candidates(db, only_closed=only_closed)
    matched = [c for c in candidates if c["team_matched"]]
    unmatched = [c for c in candidates if not c["team_matched"]]
    return {
        "total": len(candidates),
        "team_matched": len(matched),
        "team_unmatched": len(unmatched),
        "unmatched_samples": [
            {"id": c["id"], "line_major": c["line_major"], "serial_no": c["serial_no"]}
            for c in unmatched[:20]
        ],
        "headers": MD_AS_HEADERS,
        "rows_preview": [to_md_as_row(0, c) for c in matched[:20]],
    }


@router.post("/reconcile/apply")
def reconcile_apply(only_closed: bool = True, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """미리보기와 동일한 후보를 실제 통합시트 'MD AS' 탭 끝에 추가하고, 반영 확인을 위해
    통합시트를 즉시 재동기화한다(as_ticket 에도 바로 반영). 핵심 로직은 scheduler.py 의
    매일 자동 실행과 공유(ingest/geno_one_reconcile.py `apply()`)."""
    try:
        return reconcile_apply_impl(db, only_closed=only_closed)
    except RuntimeError as e:
        raise HTTPException(501, str(e))
