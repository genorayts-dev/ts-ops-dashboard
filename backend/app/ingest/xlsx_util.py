"""openpyxl 위에 얹는 얇은 헬퍼 — 앵커 탐색 / 상대 읽기 / 값 정규화."""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from typing import Any

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet


def load(raw: bytes):
    """xlsx 로드. 일부 구글시트 export 는 피벗테이블 관계(XML) 가 깨진 채 내려오는 경우가
    있어(자동화 스크립트가 시트를 재구성하면서 발생) 기본 로드가 실패하면 read_only 모드로
    재시도한다 — 이 프로젝트는 셀 값만 읽으므로(grid() 등) read_only 로도 동일하게 동작한다."""
    try:
        return openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=False)
    except Exception:
        return openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)


def grid(ws: Worksheet, *, max_rows: int = 20000, stop_after_blank: int = 80) -> list[list[Any]]:
    """
    시트를 2차원 리스트로. read_only 가 아니어야 좌표 접근이 안정적.
    일부 파일은 시트 dimension 이 1,048,576 행으로 잘못 잡혀 있어(빈 셀 서식 등)
    max_rows 상한 + 연속 빈 행 stop_after_blank 개에서 조기 종료한다.
    """
    out: list[list[Any]] = []
    blank_run = 0
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i >= max_rows:
            break
        vals = list(row)
        if any(v is not None and str(v).strip() != "" for v in vals):
            blank_run = 0
        else:
            blank_run += 1
            if blank_run >= stop_after_blank and out:
                break
        out.append(vals)
    return out


def find_anchor(g: list[list[Any]], text: str, *, contains: bool = True) -> tuple[int, int] | None:
    """text 를 포함(or 정확 일치)하는 첫 셀의 (row, col) 0-based."""
    for r, row in enumerate(g):
        for c, v in enumerate(row):
            if v is None:
                continue
            s = str(v).strip()
            if (text in s) if contains else (s == text):
                return r, c
    return None


def find_all_anchors(g: list[list[Any]], text: str) -> list[tuple[int, int]]:
    out = []
    for r, row in enumerate(g):
        for c, v in enumerate(row):
            if v is not None and text in str(v):
                out.append((r, c))
    return out


def row_values(g: list[list[Any]], r: int) -> list[Any]:
    return g[r] if 0 <= r < len(g) else []


def num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[₩$€¥￥,\s%원]", "", str(v))
    s = s.replace("CNY", "").replace("KRW", "")
    try:
        return float(s)
    except ValueError:
        return None


def as_int(v: Any) -> int | None:
    n = num(v)
    return int(round(n)) if n is not None else None


def as_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if not v:
        return None
    s = re.sub(r"\s*([.\-/])\s*", r"\1", str(v).strip()).rstrip(".")
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%m/%d", "%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def clean(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
