from __future__ import annotations

import hashlib

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from .schema import ParsedReport

# 원화 환산이 비어있을 때 fx_plan 으로 보정할 대상 컬럼
_FX_TARGETS = {
    "collection_line": ("currency", "amount", "amount_krw"),
    "receivable": ("currency", "balance", "balance_krw"),
    "as_ticket": ("repair_currency", "repair_amount", "repair_amount_krw"),
}


def _fx_table(db: Session, year: int) -> dict[str, float]:
    rows = db.execute(
        text("SELECT currency, rate_krw FROM fx_plan WHERE year = :y"), {"y": year}
    ).all()
    return {c: float(r) for c, r in rows}


def persist(db: Session, rep: ParsedReport, *, filename: str, raw: bytes, user: str) -> dict:
    if rep.period.year is None:
        raise ValueError("기간(연도) 파싱 실패 — 적재 중단")

    # 1) report_period upsert
    p = rep.period
    period_id = db.execute(
        text("""
            INSERT INTO report_period(ptype, year, month, week_no, date_start, date_end, label)
            VALUES (:ptype, :year, :month, :week_no, :ds, :de, :label)
            ON CONFLICT (ptype, year, month, week_no)
            DO UPDATE SET label = EXCLUDED.label,
                          date_start = COALESCE(EXCLUDED.date_start, report_period.date_start),
                          date_end   = COALESCE(EXCLUDED.date_end,   report_period.date_end)
            RETURNING id
        """),
        {"ptype": p.ptype, "year": p.year, "month": p.month, "week_no": p.week_no,
         "ds": p.date_start, "de": p.date_end, "label": p.label},
    ).scalar_one()

    # 2) upload_batch (트리거가 이전 active batch 를 superseded 로)
    sha = hashlib.sha256(raw).hexdigest()
    scope_key = rep.scope_key or rep.format
    batch_id = db.execute(
        text("""
            INSERT INTO upload_batch(period_id, source_name, source_sha256, source_blob,
                                     format_detected, scope_key, parser_version, status,
                                     warnings, uploaded_by)
            VALUES (:pid, :name, :sha, :blob, :fmt, :scope, :pv, 'active',
                    CAST(:warn AS JSONB), :user)
            RETURNING id
        """),
        {"pid": period_id, "name": filename, "sha": sha, "blob": raw,
         "fmt": rep.format, "scope": scope_key, "pv": settings.parser_version,
         "warn": _json(rep.warnings), "user": user},
    ).scalar_one()

    fx = _fx_table(db, p.year)

    # 3) fact bulk insert
    #    svc_summary(팀별) / monthly_trend(년·월·팀별) 는 여러 조각이 나눠 들어오므로 merge.
    summaries: dict[str, dict] = {}
    trends: dict[tuple, dict] = {}
    others: list[tuple[str, dict]] = []
    for f in rep.facts:
        row = dict(f.row)
        row["batch_id"] = batch_id
        row["period_id"] = period_id
        if f.table == "svc_summary":
            tc = row["team_code"]
            merged = summaries.setdefault(tc, {"batch_id": batch_id, "period_id": period_id, "team_code": tc})
            for k, v in row.items():
                if v is not None:
                    merged[k] = v
        elif f.table == "monthly_trend":
            key = (row["year"], row["month"], row["team_code"])
            merged = trends.setdefault(key, {"batch_id": batch_id, "period_id": period_id,
                                             "year": key[0], "month": key[1], "team_code": key[2]})
            for k, v in row.items():
                if v is not None:
                    merged[k] = v
        else:
            if f.table in _FX_TARGETS:
                cur_c, amt_c, krw_c = _FX_TARGETS[f.table]
                if row.get(krw_c) is None and row.get(cur_c) and row.get(amt_c) is not None:
                    rate = fx.get(row[cur_c])
                    if rate:
                        row[krw_c] = float(row[amt_c]) * rate
            others.append((f.table, row))

    counts: dict[str, int] = {}
    for row in summaries.values():
        _insert(db, "svc_summary", row)
        counts["svc_summary"] = counts.get("svc_summary", 0) + 1
    for row in trends.values():
        _insert(db, "monthly_trend", row)
        counts["monthly_trend"] = counts.get("monthly_trend", 0) + 1
    for table, row in others:
        _insert(db, table, row)
        counts[table] = counts.get(table, 0) + 1

    return {
        "batch_id": batch_id,
        "period_id": period_id,
        "period_label": p.label,
        "format": rep.format,
        "inserted": counts,
        "warnings": rep.warnings,
    }


def _insert(db: Session, table: str, row: dict) -> None:
    cols = ", ".join(row.keys())
    ph = ", ".join(f":{k}" for k in row)
    db.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({ph})"), row)


def _json(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
