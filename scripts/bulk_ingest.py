"""모든 주간/월간/AS xlsx 를 /api/ingest 에 업로드하고 결과를 요약."""
import glob
import os
import sys
import time

import requests

API = os.environ.get("TSD_API", "http://localhost:8000")

SOURCES = [
    r"C:\Users\genoray1\Downloads\*.xlsx",                      # 주간(다수) — 필터링
    r"C:\Users\genoray1\Desktop\*.xlsx",
    r"C:\Users\genoray1\Desktop\정명완 대리\05. 월간보고\*.xlsx",
    r"C:\Users\genoray1\Downloads\2026 AS보고서 D테크\*.xlsx",
    r"C:\Users\genoray1\Downloads\2026 AS보고서 K테크\*.xlsx",
    r"C:\Users\genoray1\Downloads\2026 AS 보고서 부산\*.xlsx",
    r"C:\Users\genoray1\Downloads\2026 AS보고서  M테크\*.xlsx",
]

# Downloads 루트에서 받을 주간/월간 파일 패턴만
DL_KEEP = ("주간회의록", "주간업무", "월간실적", "월간 실적")


def wanted(path: str) -> bool:
    name = os.path.basename(path)
    parent = os.path.basename(os.path.dirname(path))
    if parent.startswith("2026 AS"):
        return True
    if parent in ("05. 월간보고",) or parent == "Desktop":
        return name.endswith(".xlsx") and ("월간" in name or "주간" in name)
    return any(k in name for k in DL_KEEP)


files = []
for pat in SOURCES:
    for p in glob.glob(pat):
        if p.lower().endswith(".xlsx") and wanted(p):
            files.append(p)
files = sorted(set(files))
print(f"{len(files)} files to ingest\n")

ok = fail = 0
by_fmt = {}
t0 = time.time()
for i, f in enumerate(files, 1):
    name = os.path.basename(f)
    try:
        with open(f, "rb") as fh:
            r = requests.post(f"{API}/api/ingest",
                              files={"file": (name, fh,
                                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                              timeout=120)
        if r.status_code == 200:
            j = r.json()
            fmt = j["format"]
            by_fmt[fmt] = by_fmt.get(fmt, 0) + 1
            ins = sum(j["inserted"].values())
            w = len(j["warnings"])
            flag = "  ⚠" + str(w) if w else ""
            print(f"[{i:3}/{len(files)}] {fmt:11} {j['period_label']:22} rows={ins:<5}{flag}  {name[:45]}")
            ok += 1
        else:
            print(f"[{i:3}/{len(files)}] HTTP {r.status_code}  {name}  -> {r.text[:160]}")
            fail += 1
    except Exception as e:
        print(f"[{i:3}/{len(files)}] ERROR {name}: {e}")
        fail += 1

print(f"\ndone in {time.time()-t0:.0f}s   ok={ok} fail={fail}   by_format={by_fmt}")
