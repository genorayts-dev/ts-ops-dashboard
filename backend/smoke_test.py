import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from app.ingest import detect_format, parse  # noqa: E402

tests = [
    r"C:\Users\genoray1\Downloads\TS본부_주간업무(2026년 9월 1주).xlsx",
    r"C:\Users\genoray1\Downloads\TS본부_주간업무(2026년 6월 1주).xlsx",
    r"C:\Users\genoray1\Downloads\TS본부_주간회의록_1월 2주차.xlsx",
    r"C:\Users\genoray1\Downloads\[TS본부, 해외 지사] 주간회의록_2월3주차.xlsx",
    r"C:\Users\genoray1\Downloads\[TS본부]주간회의록_5월1주차.xlsx",
    r"C:\Users\genoray1\Desktop\TS본부_월간실적(2026년 08월)_rev.03.xlsx",
    r"C:\Users\genoray1\Desktop\정명완 대리\05. 월간보고\[TS본부] 월간 실적(26년 2월)_260309.xlsx",
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
        c = Counter(f.table for f in rep.facts)
        print(f"{fmt:12} | {rep.period.label:18} | facts={dict(c)} | warn={len(rep.warnings)}")
        for w in rep.warnings[:5]:
            print("   -", w)
    except Exception:
        import traceback
        print("FAIL", fn)
        traceback.print_exc()
