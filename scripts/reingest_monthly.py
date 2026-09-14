"""사용자가 첨부한 canonical 월간 실적 7개만 재적재. nginx(:8080) 경유."""
import os
import time

import requests

API = "http://localhost:8080"
FILES = [
    r"C:\Users\genoray1\Desktop\정명완 대리\05. 월간보고\[TS본부] 월간 실적 (26년 1월)_최종본(월간 발표).xlsx",
    r"C:\Users\genoray1\Desktop\정명완 대리\05. 월간보고\[TS본부] 월간 실적(26년 2월)_260309.xlsx",
    r"C:\Users\genoray1\Desktop\정명완 대리\05. 월간보고\TS본부_월간 실적(26년 3월) 260413 (최종).xlsx",
    r"C:\Users\genoray1\Desktop\정명완 대리\05. 월간보고\TS본부_월간실적(2026년 04월)_rev.02.xlsx",
    r"C:\Users\genoray1\Desktop\정명완 대리\05. 월간보고\TS본부_월간실적(2026년 05월)_rev.04.xlsx",
    r"C:\Users\genoray1\Desktop\TS본부_월간실적(2026년 06월)_rev.02.xlsx",
    r"C:\Users\genoray1\Desktop\TS본부_월간실적(2026년 08월)_rev.03.xlsx",
]
for i, f in enumerate(FILES, 1):
    name = os.path.basename(f)
    if not os.path.exists(f):
        print(f"[{i}] MISSING {name}", flush=True)
        continue
    mb = os.path.getsize(f) / 1e6
    try:
        with open(f, "rb") as fh:
            t = time.time()
            r = requests.post(f"{API}/api/ingest", files={"file": (name, fh)}, timeout=180)
        if r.status_code == 200:
            j = r.json()
            print(f"[{i}] {j['period_label']:14} {mb:4.1f}MB {time.time()-t:4.0f}s "
                  f"rows={sum(j['inserted'].values()):4} inserted={j['inserted']} w{len(j['warnings'])}", flush=True)
            for w in j["warnings"]:
                print("     ⚠", w, flush=True)
        else:
            print(f"[{i}] HTTP{r.status_code} {name}: {r.text[:160]}", flush=True)
    except Exception as e:
        print(f"[{i}] ERR {name}: {e}", flush=True)
print("DONE", flush=True)
