from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

FactTable = Literal[
    "svc_summary", "svc_region", "defect_breakdown", "equipment_stat",
    "collection_line", "receivable", "svc_case", "monthly_trend",
    "kpi_item", "svc_issue", "hr_event", "as_ticket", "plan_item",
    "maintenance_contract",
]


@dataclass
class Fact:
    table: FactTable
    row: dict[str, Any]


@dataclass
class PeriodKey:
    ptype: Literal["weekly", "monthly", "plan"]
    year: int
    month: int | None = None
    week_no: int | None = None
    date_start: date | None = None
    date_end: date | None = None
    label: str = ""


@dataclass
class ParsedReport:
    format: str
    period: PeriodKey
    facts: list[Fact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # 같은 기간 안에서 서로 덮어써야 하는 단위. 기본은 format(weekly/monthly),
    # AS 대장은 파서가 'as:<org>:<product_line>' 로 세팅.
    scope_key: str | None = None

    def add(self, table: FactTable, **row: Any) -> None:
        self.facts.append(Fact(table, row))

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
