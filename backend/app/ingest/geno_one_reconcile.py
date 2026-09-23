"""
geno_one_ticket ↔ as_ticket(통합시트 유래, org D/M) 교차검증 + 통합시트 'MD AS' 탭 반영.

매칭 기준: 제조번호(serial_no) 동일 + 접수일 차이 3일 이내 → 이미 통합시트에 있는
것으로 간주. 매치 없는 행만 후보. 팀(D/M) 은 geno-one 원본에 없어서(해외 AS관리는
팀 구분 없이 단일 목록) 기존 as_ticket 의 제품명→팀 통계로 추론한다:
  1순위: 정확한 모델명 매칭(기존에 나온 그 모델 그대로).
  2순위(폴백): 제품군 분류(_LINE_PATTERNS, 예: PORT-X* → PORTABLE) 기준 — 이 분류가
     기존 데이터에서 한쪽 팀에만 나타날 때만("순도 100%") 채택. C-ARM/MAMMO=M테크,
     CT/SENSOR/PANO/DVAS/PORTABLE=D테크 로 완전히 갈림(교차 사례 0건, 검증 완료).
     이 폴백 덕에 "PORT-X IV"처럼 정확 표기가 기존 시트에 없는 신모델도 PORTABLE→D
     로 정상 매칭됨(사용자 지적으로 발견·수정, 2026-09-21).

**완료(Close) 상태만 반영 대상으로 제한한다** — New/Inprogress/Holding 은 아직
조치사항·결과·불량구분이 비어 있어(수집 시점 스냅샷) 그대로 넣으면 통합시트의
"완료된 AS 이력" 관례와 안 맞고, 나중에 담당자가 완료 후 수동으로 또 넣으면
중복이 생김. 열린 티켓은 통계/후속조치 용도로만 조회하고 시트엔 안 넣는다.

**GK 채널이거나(charge_type='본사' 필수), 담당자가 한국 본사 엔지니어 명단에 있는
(법인 접점이면 charge_type 무관) 티켓만 대상으로 한다.**
geno-one 의 charge_type 라벨은 신뢰할 수 없다는 게 두 번 확인됐음 — GS 인 건의
charge_type='본사' 는 제노레이코리아 본사가 아니라 **제노레이 상하이(Genoray
Shanghai) 소속 중국인 엔지니어**를 가리켰고(서전천/진초/왕건군, 2026-09-21),
GT 인 건은 반대로 한국 본사 엔지니어(한재형)가 처리했는데도 charge_type='딜러사'
로 찍혀 있었음(2026-09-22). 그래서 두 조건 중 하나를 만족해야 포함한다:
  1) Contact Point 가 GK(외부 대리점 채널)이고, 그 대리점의 자체 기술진이 아니라
     **한국 본사 엔지니어가 직접 출동해 처리한 건**(charge_type='본사') — 여기선
     charge_type 이 "대리점 자체처리 vs 본사 출동"을 구분하는 유일한 신호라 계속
     사용한다.
  2) Contact Point 가 GS/GT/GJ/GAI/GEG(제노레이 해외법인 접점)면, charge_type 값과
     무관하게 **담당자 이름이 한국 본사 엔지니어 명단에 있으면** 포함한다(사용자
     확인, 2026-09-22 — "법인 접점 건이라도 한국 본사 직원이 처리했으면 넣어
     달라"). 명단은 `_korea_hq_engineers()` 가 GK+본사 버킷에 실제 등장한 담당자
     이름에서 자동 추출하되, 서전천/왕건군/진초(상하이 법인 확정 직원)는 그
     버킷에도 소량 섞여 나타나므로(오분류 추정) 명시적으로 제외한다 — 그대로
     뒀다간 이 세 사람이 처리한 GS 100여 건이 전부 "한국 본사 처리"로 오매칭되는
     걸 실제로 확인했음.

**시행착오 기록**(같은 실수를 반복하지 않기 위해 남김):
1) 처음엔 필터 없이 Close 상태 111건을 다 넣음.
2) "Contact Point=GK 만" 기준으로 잘못 좁혀 법인(GS/GT/GJ) 응대 24건을 지움 —
   그런데 사용자가 "법인이라도 우리가(본사가) 처리했으면 넣어야 한다"고 정정.
3) 기준을 "charge_type=본사"로 바꿔 24건 중 21건(GS 20+GT 1)을 재삽입 —
   그런데 서전천/진초/왕건군 같은 이름을 사용자가 보고 "이 사람들은 상하이
   법인 소속이지 본사 아니다"라고 재정정 → **본사=charge_type 라벨이 곧
   한국 본사를 뜻하지 않는다**는 게 드러남.
4) GK(채널) AND 본사(charge_type) 둘 다 만족해야 포함 — 3)에서 재삽입한
   21건 다시 제거, GK인데 대리점이 자체처리한 19건도 별도로 제거.
5) (2026-09-22) 사용자가 "GK 채널이 아니어도 법인 것도 한국 본사 직원이 처리하면
   넣어달라"고 재확인 — GS/GT/GJ 담당자 명단을 까보니 GJ 3건·GT 2건(한준희/
   한재형/임지민/임창언)은 실제 한국 이름이라 4)의 GK-only 기준이 너무 좁았음.
   명단을 GK+본사 버킷에서 자동 추출하려다 함정 발견: 서전천/왕건군이 그 버킷에도
   소량(3건/1건) 섞여 있어 자동 추출 그대로 쓰면 GS 소속 서전천/왕건군 건(100여
   건)까지 전부 매칭돼버림 — 3)에서 이미 상하이 직원으로 확정한 사람들인데
   자동화가 그 결론을 뒤집을 뻔함. 서전천/왕건군/진초를 명단에서 명시적으로
   제외(`_SHANGHAI_BLOCKLIST`)하는 걸로 해결.
6) (2026-09-22) 5) 적용 후 법인 쪽엔 charge_type='본사' 조건도 같이 걸어놨었는데,
   사용자가 "GT인데 한재형인 건을 본 것 같다"고 지적 — 찾아보니 GT 한재형 4건이
   실제 있었고 전부 charge_type='딜러사' 로 찍혀 있었음(그 중 2건은 이미 시트에
   있어 제외, 2건은 진짜 신규). charge_type 라벨이 GS('본사'=상하이 직원)에 이어
   GT('딜러사'인데 실제론 본사 직원)에서도 또 신뢰 못 할 라벨로 확인됨 → **법인
   쪽은 charge_type 조건을 아예 빼고 담당자 이름 화이트리스트 매칭만으로 판단**
   하도록 변경(GK 쪽은 charge_type='본사' 조건 유지 — 대리점 자체처리와 구분하는
   용도로는 여전히 유효했음). 딜러사 라벨 법인 건 19건 전수 확인 결과 화이트리스트
   매칭은 한재형 4건뿐이라 조건 완화로 인한 범람은 없음(검증 완료).
"""
from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from .gsheet_master import _LINE_PATTERNS

MD_AS_HEADERS = [
    "No.", "팀", "유형", "접수일", "조치일", "지역", "국가/거래처",
    "제품분류", "제품명(사양)", "제조번호/코드", "보증구분", "담당자",
    "증상/내용", "조치사항", "불량구분", "결과",
]

# geno-one 이 모델 뒤 숫자를 로마 숫자로 적는 경우가 있음("PORT-X IV" = "PORT-X 4",
# 사용자 지적으로 발견) — 정규화 전에 아라비아 숫자로 치환해서 시트의 기존 표기와
# 맞춰준다("PORT-X 4" 가 드롭다운에 이미 있으므로 이렇게 해야 빈칸 대신 채워짐).
# 문자열 맨 끝에 올 때만 치환 — "PORT-X" 처럼 모델명 중간에 오는 'X' 를 로마 숫자
# 10 으로 잘못 치환해버리면(예: "PORT-X 4" 의 'X') 서로 다른 모델이 우연히 같은
# 정규화 결과로 뭉쳐질 위험이 있어서, 끝단 버전 표기에만 한정한다.
_ROMAN = {"IX": "9", "IV": "4", "VIII": "8", "VII": "7", "VI": "6",
          "III": "3", "II": "2", "V": "5", "X": "10", "I": "1"}
_ROMAN_RE = re.compile(r"\b(" + "|".join(_ROMAN) + r")\b$")


def _norm(s: str | None) -> str:
    s = _ROMAN_RE.sub(lambda m: _ROMAN[m.group(1)], (s or "").upper())
    return "".join(ch for ch in s if ch.isalnum())


def _classify_line(model: str | None) -> str:
    if model:
        for pat, cat in _LINE_PATTERNS:
            if pat.search(model):
                return cat
    return ""


def _team_lookup(db: Session) -> dict[str, tuple[str, str]]:
    """product_model(정규화) → (org, 정식 모델 표기). 통합시트 '제품명(사양)' 열에
    드롭다운 데이터 검증(정해진 모델명 목록만 허용)이 걸려 있어서(2026-09-21,
    실제 삽입 시도 중 발견 — "I1211 셀... 데이터 확인 규칙을 위반합니다" 에러로
    확인), geno-one 원본 표기("OSCAR-15FD")를 그대로 넣으면 시트의 정식 표기
    ("OSCAR-15 FD", 공백 있음)와 달라 전체 배치가 거부된다. 그래서 정확히 매칭된
    경우 시트에 이미 있는 정식 표기(model, as_ticket.product_model 원문)를 그대로
    돌려주고, to_md_as_row() 가 그 값을 쓴다."""
    rows = db.execute(text("""
        SELECT product_model, org, count(*) n
          FROM as_ticket a JOIN v_latest_batch lb ON lb.batch_id = a.batch_id
         WHERE a.src = 'md_service' AND a.org IN ('D', 'M') AND product_model IS NOT NULL
         GROUP BY 1, 2
    """)).all()
    best: dict[str, tuple[str, str, int]] = {}
    for model, org, n in rows:
        key = _norm(model)
        if key and (key not in best or n > best[key][2]):
            best[key] = (org, model, n)
    return {k: (v[0], v[1]) for k, v in best.items()}


def _category_lookup(db: Session) -> dict[str, str]:
    """제품군 분류(_LINE_PATTERNS) → org. 한쪽 팀에만 나타나는(순도 100%) 분류만 채택
    — 새 모델 표기(정확 매칭 실패)에 대한 폴백용이라 애매하면 아예 안 넣는 게 안전."""
    rows = db.execute(text("""
        SELECT DISTINCT product_model, org
          FROM as_ticket a JOIN v_latest_batch lb ON lb.batch_id = a.batch_id
         WHERE a.src = 'md_service' AND a.org IN ('D', 'M') AND product_model IS NOT NULL
    """)).all()
    cat_orgs: dict[str, set[str]] = {}
    for model, org in rows:
        cat = _classify_line(model)
        if cat:
            cat_orgs.setdefault(cat, set()).add(org)
    return {cat: next(iter(orgs)) for cat, orgs in cat_orgs.items() if len(orgs) == 1}


_SHANGHAI_BLOCKLIST = {"서전천", "왕건군", "진초"}
_CORP_CONTACT_POINTS = ("GS", "GT", "GJ", "GAI", "GEG")

_ENGINEER_SUFFIX_RE = [
    re.compile(r"\s*manager\s*$", re.IGNORECASE),
    re.compile(r"\s*등\s*\d+\s*명\s*$"),
]


def _strip_engineer_suffix(name: str | None) -> str:
    """담당자 필드에 붙는 '... manager', '... 등 N명' 같은 꼬리표를 반복 제거해
    이름만 남긴다(예: '정종남 manager 등 2명' → '정종남')."""
    prev = None
    n = (name or "").strip()
    while prev != n:
        prev = n
        for pat in _ENGINEER_SUFFIX_RE:
            n = pat.sub("", n).strip()
    return n


def _korea_hq_engineers(db: Session) -> set[str]:
    """GK 채널을 한국 본사 직원이 직접 처리한 건(contact_point='GK' AND
    charge_type='본사')에 실제로 등장한 담당자 이름 집합. 법인(GS/GT/GJ/GAI/GEG)
    접점 건이라도 여기 있는 이름이 담당자로 나오면 '한국 본사가 처리한 건'으로
    함께 포함한다(사용자 확인, 2026-09-22). `_SHANGHAI_BLOCKLIST` 는 이 버킷에도
    소량 섞여 나타나지만 이미 상하이 법인 소속으로 확정된 사람들이라 제외한다."""
    rows = db.execute(text("""
        SELECT DISTINCT g.engineer
          FROM geno_one_ticket g JOIN v_latest_batch lb ON lb.batch_id = g.batch_id
         WHERE g.contact_point = 'GK' AND g.charge_type = '본사'
    """)).all()
    names = {_strip_engineer_suffix(r[0]) for r in rows}
    names.discard("")
    return names - _SHANGHAI_BLOCKLIST


def find_candidates(db: Session, *, only_closed: bool = True) -> list[dict]:
    model_lookup = _team_lookup(db)
    cat_lookup = _category_lookup(db)
    hq_engineers = _korea_hq_engineers(db)
    status_clause = "AND g.service_status = 'Close'" if only_closed else ""
    rows = db.execute(text(f"""
        SELECT g.id, g.seq_no, g.dealer_country, g.line_major, g.product_name,
               g.serial_no, g.warranty_paid, g.engineer, g.fix_class, g.result,
               g.action_taken, g.detail, g.ticket_type, g.received_date,
               g.action_date, g.service_status, g.contact_point
          FROM geno_one_ticket g
          JOIN v_latest_batch glb ON glb.batch_id = g.batch_id
         WHERE g.serial_no IS NOT NULL
           AND (
                (g.contact_point = 'GK' AND g.charge_type = '본사')
                OR g.contact_point IN ({", ".join("'%s'" % c for c in _CORP_CONTACT_POINTS)})
           )
           {status_clause}
           AND NOT EXISTS (
                SELECT 1 FROM as_ticket a JOIN v_latest_batch alb ON alb.batch_id = a.batch_id
                 WHERE a.serial_no = g.serial_no AND a.org IN ('D', 'M')
                   AND abs(a.received_date - g.received_date) <= 3
           )
         ORDER BY g.received_date
    """)).mappings().all()

    out = []
    for r in rows:
        d = dict(r)
        if d["contact_point"] != "GK":
            engineer = d["engineer"] or ""
            if not any(name in engineer for name in hq_engineers):
                continue
        model = d["line_major"]
        hit = model_lookup.get(_norm(model))
        if hit:
            org, canonical_model, match_basis = hit[0], hit[1], "model"
        else:
            org = cat_lookup.get(_classify_line(model))
            # 카테고리로만 팀을 추론한 경우 시트 드롭다운엔 없는 모델이란 뜻이라
            # 제품명(사양) 칸은 비워둔다(검증 규칙 위반으로 전체 삽입이 막히는 것 방지).
            canonical_model, match_basis = None, ("category" if org else None)
        d["org"] = org
        d["canonical_model"] = canonical_model
        d["team_matched"] = org is not None
        d["match_basis"] = match_basis
        out.append(d)
    return out


def apply(db: Session, *, only_closed: bool = True) -> dict:
    """find_candidates() 결과 중 팀 매칭된 것만 통합시트 'MD AS' 탭에 실제로 추가하고
    반영 확인을 위해 통합시트를 즉시 재동기화한다(as_ticket 에도 바로 반영).
    라우터(/api/geno_one/reconcile/apply)와 scheduler.py(매일 자동 실행) 양쪽에서
    공유하는 핵심 로직 — 실패 시 일반 예외를 던지므로 호출부가 각자 맞게 처리한다."""
    from .. import gsheet
    from . import parse
    from .gsheet_master import _tab_any
    from .persist import persist
    from .xlsx_util import grid, load

    if not gsheet.can_write():
        raise RuntimeError(
            "통합시트 쓰기 권한이 없습니다 — deploy/apps_script_append.gs 를 시트에 배포하고 "
            "TSD_GENO_ONE_SHEET_WEBHOOK_URL/TSD_GENO_ONE_SHEET_SECRET 을 설정하세요."
        )
    row = db.execute(text("SELECT sheet_id FROM gsheet_source ORDER BY id LIMIT 1")).first()
    if not row:
        raise RuntimeError("통합 구글시트가 등록되지 않았습니다 (데이터 관리 탭에서 먼저 등록하세요).")
    sheet_id = row[0]

    candidates = find_candidates(db, only_closed=only_closed)
    matched = [c for c in candidates if c["team_matched"]]
    if not matched:
        return {"inserted": 0, "skipped_unmatched": len(candidates)}

    raw, _ = gsheet.fetch_xlsx(sheet_id)
    wb = load(raw)
    tab = _tab_any(wb, ("MD서비스",), ("MD방문",), ("MD서비스건수",), ("MD", "AS"))
    if not tab:
        raise RuntimeError("통합시트에서 'MD AS' 탭을 찾지 못했습니다(탭 이름이 또 바뀌었을 수 있음).")
    max_no = 0
    for r in grid(wb[tab]):
        try:
            max_no = max(max_no, int(r[0]))
        except (TypeError, ValueError, IndexError):
            continue

    rows = [to_md_as_row(max_no + 1 + i, c) for i, c in enumerate(matched)]
    # 정확한 tab 대신 needles 로 보내 Apps Script 가 호출 시점에 실시간으로 탭을
    # 찾게 한다(위 tab 은 next_no 계산용 export 스냅샷 기준이라 stale 할 수 있음).
    gsheet.append_rows(rows, tab_needles=["MD", "AS"])

    raw2, name = gsheet.fetch_xlsx(sheet_id)
    parsed = parse(raw2, name)
    sync_res = persist(db, parsed, filename=name, raw=raw2, user="geno_one_reconcile")

    return {
        "inserted": len(rows),
        "skipped_unmatched": len(candidates) - len(matched),
        "tab": tab,
        "resync": sync_res,
    }


def to_md_as_row(no: int, c: dict) -> list:
    team_label = {"D": "D테크", "M": "M테크"}.get(c["org"], "")
    return [
        no,
        team_label,
        "서비스",
        c["received_date"].isoformat() if c["received_date"] else "",
        c["action_date"].isoformat() if c["action_date"] else "",
        "",
        c["dealer_country"] or "",
        _classify_line(c["line_major"]),
        c["canonical_model"] or "",  # 드롭다운 검증 위반 방지 — 비정식 표기는 빈칸
        c["serial_no"] or "",
        c["warranty_paid"] or "",
        c["engineer"] or "",
        c["detail"] or "",
        c["action_taken"] or "",
        c["fix_class"] or "",
        c["result"] or "",
    ]
