from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..ingest import parse
from ..ingest.persist import persist

router = APIRouter(prefix="/api", tags=["ingest"])

_MAX_BYTES = 100 * 1024 * 1024


@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm", ".xls", ".pdf")):
        raise HTTPException(400, "엑셀(.xlsx) 또는 월간보고 PDF만 업로드할 수 있습니다.")
    raw = await file.read()
    if len(raw) > _MAX_BYTES:
        raise HTTPException(413, f"파일이 {_MAX_BYTES // (1024*1024)}MB를 초과합니다.")

    try:
        parsed = parse(raw, file.filename)
    except ValueError as e:
        raise HTTPException(422, f"양식 파싱 실패: {e}")
    except Exception as e:  # openpyxl 로드 실패 등 (손상 파일·비-xlsx 등)
        raise HTTPException(422, f"파일을 열 수 없습니다: {type(e).__name__}: {e}")

    try:
        result = persist(db, parsed, filename=file.filename, raw=raw, user=user)
    except Exception as e:
        raise HTTPException(500, f"적재 중 오류: {type(e).__name__}: {e}")
    return {"ok": True, **result}


@router.get("/batches")
def list_batches(db: Session = Depends(get_db), limit: int = 100):
    rows = db.execute(_BATCHES_SQL, {"limit": limit}).mappings().all()
    return list(rows)


@router.post("/batches/{batch_id}/rollback")
def rollback(batch_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """이 batch 를 failed 로 내리고, 같은 (period, format) 의 직전 batch 를 다시 active 로."""
    from sqlalchemy import text

    row = db.execute(
        text("SELECT period_id, scope_key FROM upload_batch WHERE id=:id"), {"id": batch_id}
    ).one_or_none()
    if not row:
        raise HTTPException(404, "batch 없음")
    db.execute(text("UPDATE upload_batch SET status='failed' WHERE id=:id"), {"id": batch_id})
    db.execute(
        text("""
            UPDATE upload_batch SET status='active'
            WHERE id = (
                SELECT id FROM upload_batch
                WHERE period_id=:pid AND scope_key=:scope AND id<>:id AND status='superseded'
                ORDER BY uploaded_at DESC LIMIT 1
            )
        """),
        {"pid": row.period_id, "scope": row.scope_key, "id": batch_id},
    )
    return {"ok": True, "rolled_back": batch_id, "by": user}


from sqlalchemy import text  # noqa: E402

_BATCHES_SQL = text("""
    SELECT b.id, b.status, b.format_detected, b.source_name, b.uploaded_by, b.uploaded_at,
           p.label AS period_label, p.ptype,
           jsonb_array_length(b.warnings) AS warning_count
      FROM upload_batch b JOIN report_period p ON p.id = b.period_id
     ORDER BY b.uploaded_at DESC
     LIMIT :limit
""")
