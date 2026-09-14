from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db

router = APIRouter(prefix="/api/annotations", tags=["annotations"])

_SCOPES = {"period", "issue", "kpi", "receivable", "case"}


class NewAnnotation(BaseModel):
    scope: str
    ref_id: int
    body: str


@router.get("")
def list_annotations(scope: str, ref_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT id, body, author, created_at, resolved
          FROM annotation WHERE scope = :s AND ref_id = :r ORDER BY created_at
    """), {"s": scope, "r": ref_id}).mappings().all()
    return list(rows)


@router.post("")
def add_annotation(a: NewAnnotation, db: Session = Depends(get_db), user: str = Depends(current_user)):
    if a.scope not in _SCOPES:
        return {"ok": False, "error": "invalid scope"}
    aid = db.execute(text("""
        INSERT INTO annotation(scope, ref_id, body, author) VALUES (:s, :r, :b, :u) RETURNING id
    """), {"s": a.scope, "r": a.ref_id, "b": a.body, "u": user}).scalar_one()
    return {"ok": True, "id": aid}


@router.post("/{aid}/resolve")
def resolve(aid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    db.execute(text("UPDATE annotation SET resolved = TRUE WHERE id = :id"), {"id": aid})
    return {"ok": True, "by": user}
