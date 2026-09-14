import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from app.ingest import detect_format, parse  # noqa: E402

tests = [
    r"C:\Users\genoray1\Downloads\2026 AS보고서 D테크\덴탈 대장비_해외 AS접수처리대장(26년1월).xlsx",
    r"C:\Users\genoray1\Downloads\2026 AS보고서 D테크\덴탈 소장비_해외 AS접수처리대장(26년7월).xlsx",
    r"C:\Users\genoray1\Downloads\2026 AS보고서 K테크\AS보고서 C-ARM_26년 8월.xlsx",
    r"C:\Users\genoray1\Downloads\2026 AS보고서 K테크\AS보고서 DENTAL STANDARD_26년 3월.xlsx",
    r"C:\Users\genoray1\Downloads\2026 AS보고서 K테크\AS보고서 MAMMO_26년 5월.xlsx",
    r"C:\Users\genoray1\Downloads\2026 AS 보고서 부산\부산지사 AS보고서 CARM_01월.xlsx",
    r"C:\Users\genoray1\Downloads\2026 AS보고서  M테크\해외 AS보고서 C-Arm 26년 1월.xlsx",
    r"C:\Users\genoray1\Downloads\2026 AS보고서  M테크\해외 AS보고서 MAMMO 26년 7월.xlsx",
]

for t in tests:
    fn = os.path.basename(t)
    if not os.path.exists(t):
        print("MISSING", fn)
        continue
    raw = open(t, "rb").read()
    try:
        fmt = detect_format(raw, fn)
        rep = parse(raw, fn)
        tickets = [f.row for f in rep.facts if f.table == "as_ticket"]
        c = Counter(f.table for f in rep.facts)
        sample = tickets[0] if tickets else {}
        orgs = Counter(x["org"] for x in tickets)
        overseas = sum(1 for x in tickets if x["is_overseas"])
        with_cost = sum(1 for x in tickets if x["repair_amount"])
        print(f"{fmt} | scope={rep.scope_key} | {rep.period.label} | {dict(c)} | "
              f"org={dict(orgs)} overseas={overseas} cost>0={with_cost} warn={len(rep.warnings)}")
        for w in rep.warnings[:3]:
            print("   -", w)
        if sample:
            print("   e.g.:", {k: sample[k] for k in
                  ("shipped_to", "country", "product_model", "warranty",
                   "received_date", "result", "repair_currency", "repair_amount",
                   "cause", "fix_class")})
    except Exception:
        import traceback
        print("FAIL", fn)
        traceback.print_exc()
