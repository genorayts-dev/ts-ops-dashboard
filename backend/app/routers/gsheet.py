from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import gsheet
from ..auth import current_user
from ..db import get_db
from ..ingest import parse
from ..ingest.persist import persist

router = APIRouter(prefix="/api/gsheet", tags=["gsheet"])


class SheetIn(BaseModel):
    url: str
    note: str | None = None


@router.get("/status")
def status(db: Session = Depends(get_db)):
    if not gsheet.enabled():
        return {"enabled": False, "sources": []}
    rows = db.execute(text("""
        SELECT id, sheet_id, title, note, added_by, added_at, last_sync_at, last_status
          FROM gsheet_source ORDER BY added_at
    """)).mappings().all()
    return {"enabled": True, "sources": list(rows)}


@router.post("/sources")
def add_source(s: SheetIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    if not gsheet.enabled():
        raise HTTPException(501, "구글 시트 연동이 설정되지 않았습니다 (TSD_GOOGLE_SA_JSON).")
    sid = gsheet.extract_id(s.url)
    if not sid:
        raise HTTPException(400, "스프레드시트 URL 또는 ID 를 확인하세요.")
    db.execute(text("""
        INSERT INTO gsheet_source(sheet_id, note, added_by) VALUES (:sid, :note, :user)
        ON CONFLICT (sheet_id) DO UPDATE SET note = EXCLUDED.note
    """), {"sid": sid, "note": s.note, "user": user})
    return {"ok": True, "sheet_id": sid}


@router.delete("/sources/{sid}")
def del_source(sid: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM gsheet_source WHERE id = :id"), {"id": sid})
    return {"ok": True}


def _sync_one(db: Session, row, user: str) -> dict:
    try:
        raw, name = gsheet.fetch_xlsx(row["sheet_id"])
        parsed = parse(raw, name)
        res = persist(db, parsed, filename=name, raw=raw, user=f"gsheet:{user}")
        db.execute(text("""
            UPDATE gsheet_source SET last_sync_at = now(), last_status = 'ok',
                   title = :t, last_batch_id = :b WHERE id = :id
        """), {"t": name, "b": res["batch_id"], "id": row["id"]})
        return {"sheet_id": row["sheet_id"], "ok": True, **res}
    except Exception as e:
        db.execute(text("""
            UPDATE gsheet_source SET last_sync_at = now(), last_status = :s WHERE id = :id
        """), {"s": f"error: {type(e).__name__}: {e}"[:300], "id": row["id"]})
        return {"sheet_id": row["sheet_id"], "ok": False, "error": f"{type(e).__name__}: {e}"}


@router.post("/sync")
def sync(id: int | None = None, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """id 지정 시 그 소스만, 없으면 전체 동기화."""
    if not gsheet.enabled():
        raise HTTPException(501, "구글 시트 연동이 설정되지 않았습니다.")
    q = "SELECT id, sheet_id FROM gsheet_source" + (" WHERE id = :id" if id else "")
    rows = db.execute(text(q), {"id": id} if id else {}).mappings().all()
    if not rows:
        raise HTTPException(404, "동기화할 시트가 없습니다.")
    return {"results": [_sync_one(db, r, user) for r in rows]}
