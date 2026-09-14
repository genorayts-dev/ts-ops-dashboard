"""
gsheet_plan: 2026 TS본부 사업계획(업무 세부 실행계획) 구글 시트 → plan_item

시트 구조 (탭 '1. 진행 현황' 기준):
  ■ TS본부 2026 업무 세부 실행계획
  1. 서비스 고도화                              ← 분류 헤더
  구분 | ... | 1분기 | ...                       ← 분기 라벨행 (무시)
  실행계획 | 담당 | 목표 | 세부 내용 | 1월..12월 | 기대 효과   ← 헤더행
  <과제행>  실행계획·담당은 병합 → forward-fill
  ...
  2. 서비스 상품화  / 3. 조직 역량 강화 ← 다음 분류

grain: (실행계획 또는 담당) 이 새로 나오면 새 plan_item.
       그 아래 c1·c2 가 빈 연속행(목표 bullet 만 있는 행)은 위 항목에 병합.
연간 목표 건수: 목표 텍스트의 '총 N건' / '(N회)' / '누적 N건' / '월 1회'(=12) 파싱.
월별 계획: 각 월 칸 텍스트를 병합행까지 합쳐서 저장(JSON 문자열).

하나의 batch. scope_key='gsheet_plan' → 재동기화 시 이전 batch 대체.
"""
from __future__ import annotations

import json
import re

from .schema import ParsedReport, PeriodKey
from .xlsx_util import clean, grid, load, num

_CATS = ("서비스 고도화", "서비스 상품화", "조직 역량 강화")
_CAT_RE = re.compile(r"^\s*\d+\.\s*(서비스\s*고도화|서비스\s*상품화|조직\s*역량\s*강화)")


def detect(wb) -> bool:
    names = [n.replace(" ", "") for n in wb.sheetnames]
    if not any(("사업계획" in n) or ("진행현황" in n) or ("실행계획" in n) for n in names):
        return False
    # 본문에 '업무 세부 실행계획' 앵커가 있으면 확정
    for s in wb.worksheets:
        for row in s.iter_rows(min_row=1, max_row=8, values_only=True):
            if any(v and "실행계획" in str(v) for v in row):
                return True
    return False


def _pick_sheet(wb):
    """링크로 공유된 '진행 현황' 탭 우선. (원본/사본 초안 제외)"""
    cand = []
    for n in wb.sheetnames:
        s = n.replace(" ", "")
        if "진행현황" in s and not s.endswith(("1)", "(원본)")):
            cand.append(n)
    if cand:
        return cand[0]
    # 폴백: ■ 실행계획 구조가 있는 첫 시트
    for n in wb.sheetnames:
        g = grid(wb[n], max_rows=10)
        for row in g:
            if any(v and "실행계획" in str(v) and "세부" not in str(v) for v in row):
                return n
    return wb.sheetnames[0]


def _team_code(raw: str | None):
    if not raw:
        return None
    r = raw.replace(" ", "")
    letters = [x for x in ("D", "M", "K") if f"{x}테크" in r]
    if len(letters) == 1:
        return letters[0]
    return None  # TS본부 / 공통 / 운영지원팀 / 다팀(D/M)


def _total_n(text: str | None):
    """'총 N건' 류 — 그룹 전체 목표(권위값)."""
    if not text:
        return None
    t = text.replace(" ", "")
    for pat in (r"총[:：]?(\d+)건", r"\((\d+)회\)", r"(\d+)회\)", r"누적(\d+)건", r"누계(\d+)건", r"\((\d+)건\)"):
        m = re.search(pat, t)
        if m:
            return int(m.group(1))
    if "월1회" in t:
        return 12
    return None


def _bullet_n(text: str | None):
    """'• PAPAYA : 7건' 류 — bullet 단위 건수."""
    if not text:
        return None
    m = re.search(r"[:：]\s*(\d+)\s*건", text)
    return int(m.group(1)) if m else None


def _compute_goal_n(goals: list[str]):
    tots = [n for n in (_total_n(g) for g in goals) if n]
    if tots:
        return max(tots)
    bullets = [n for n in (_bullet_n(g) for g in goals) if n]
    return sum(bullets) if bullets else None


def _is_prose(goal: str | None, detail: str | None, months: list[str]) -> bool:
    """계획이 아니라 설명 문장인 행: 건수·세부·월 활동이 하나도 없으면 과제로 보지 않음."""
    if _total_n(goal) or _bullet_n(goal):
        return False
    if detail or any(months):
        return False
    return True


def _month_row(row: list, c0: int) -> list[str]:
    out = []
    for i in range(12):
        v = clean(row[c0 + i]) if c0 + i < len(row) else None
        out.append(v or "")
    return out


def _all_numeric(row: list, c0: int) -> bool:
    seen = False
    for i in range(12):
        v = row[c0 + i] if c0 + i < len(row) else None
        if v is None or str(v).strip() == "":
            continue
        n = num(v)
        if n is None or n < 0 or n > 1.0001:
            return False
        seen = True
    return seen


def parse_gsheet_plan(raw: bytes, filename: str) -> ParsedReport:
    wb = load(raw)
    rep = ParsedReport("gsheet_plan", PeriodKey(ptype="plan", year=2026,
                                                label="2026 사업계획"))
    rep.scope_key = "gsheet_plan"

    sheet = _pick_sheet(wb)
    g = grid(wb[sheet], max_rows=400)

    # 헤더행에서 열 위치 파악 (분류마다 반복되지만 레이아웃 동일하다고 가정, 첫 헤더 사용)
    c_plan = c_team = c_goal = c_detail = c_m1 = c_expect = None
    for row in g:
        cells = [clean(c) for c in row]
        if "실행계획" in cells and "목표" in cells:
            c_plan = cells.index("실행계획")
            c_goal = cells.index("목표")
            c_detail = cells.index("세부 내용") if "세부 내용" in cells else (
                cells.index("세부내용") if "세부내용" in cells else c_goal + 1)
            c_team = cells.index("담당") if "담당" in cells else c_plan + 1
            c_m1 = cells.index("1월") if "1월" in cells else c_detail + 1
            c_expect = cells.index("기대 효과") if "기대 효과" in cells else None
            break
    if c_plan is None:
        rep.warn("사업계획: 헤더행(실행계획/목표) 못 찾음")
        return rep

    cat = None
    seq = 0
    cur: dict | None = None
    last_plan: str | None = None

    def flush():
        nonlocal cur
        if not cur:
            return
        months = {str(i + 1): "\n".join(x for x in cur["months"][i] if x).strip()
                  for i in range(12)}
        prog = {str(k): v for k, v in cur["progress"].items()}
        goal_join = " / ".join(dict.fromkeys(cur["goals"]))
        rep.add(
            "plan_item",
            category=cur["cat"],
            plan_name=cur["plan"],
            team_code=_team_code(cur["team"]),
            team_label=(cur["team"] or "").strip() or None,
            goal_text=goal_join or None,
            goal_n=_compute_goal_n(cur["goals"]),
            detail=(" / ".join(dict.fromkeys(cur["details"])) or None),
            expect=cur["expect"],
            months=json.dumps(months, ensure_ascii=False),
            progress=json.dumps(prog, ensure_ascii=False),
            seq=cur["seq"],
        )
        cur = None

    for row in g:
        plan_v = clean(row[c_plan]) if c_plan < len(row) else None
        # 분류 헤더
        if plan_v:
            m = _CAT_RE.match(plan_v)
            if m:
                flush()
                cat = re.sub(r"\s+", " ", m.group(1))
                last_plan = None
                continue
            if plan_v in ("구분", "실행계획"):
                continue
            last_plan = plan_v
        team_v = clean(row[c_team]) if c_team is not None and c_team < len(row) else None
        goal_v = clean(row[c_goal]) if c_goal < len(row) else None
        detail_v = clean(row[c_detail]) if c_detail is not None and c_detail < len(row) else None
        months = _month_row(row, c_m1)
        expect_v = clean(row[c_expect]) if c_expect is not None and c_expect < len(row) else None

        # 진행률 행 (c1..c4 비고 월 칸이 전부 0~1 숫자) → 직전 항목에 부착
        if cur and not plan_v and not team_v and not goal_v and not detail_v and _all_numeric(row, c_m1):
            for i in range(12):
                v = row[c_m1 + i] if c_m1 + i < len(row) else None
                n = num(v)
                if n is not None:
                    cur["progress"][i + 1] = n
            continue

        starts_new = bool(plan_v or team_v)
        if starts_new:
            if _is_prose(goal_v, detail_v, months):
                # 설명 문장 행: 새 항목 만들지 않음. 단 후속 병합 방지 위해 flush.
                flush()
                if plan_v:
                    cur = None
                continue
            flush()
            seq += 1
            cur = {
                "cat": cat, "plan": plan_v or last_plan, "team": team_v, "seq": seq,
                "goals": [goal_v] if goal_v else [],
                "details": [detail_v] if detail_v else [],
                "expect": expect_v,
                "months": [[m] for m in months],
                "progress": {},
            }
        else:
            if cur is None:
                continue
            if goal_v:
                cur["goals"].append(goal_v)
            if detail_v:
                cur["details"].append(detail_v)
            for i in range(12):
                if months[i]:
                    cur["months"][i].append(months[i])
            if expect_v and not cur["expect"]:
                cur["expect"] = expect_v

    flush()

    n = sum(1 for f in rep.facts if f.table == "plan_item")
    if n == 0:
        rep.warn("사업계획: 실행과제 0건 파싱")
    return rep
