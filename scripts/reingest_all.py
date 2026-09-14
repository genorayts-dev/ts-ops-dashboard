"""AS 82 + 월간 7 재적재 (파서 개선분 반영). nginx(:8080) 경유."""
import glob
import os
import time

import requests

API = "http://localhost:8080"
groups = {
    "AS": [f for fo in [
        r"C:\Users\genoray1\Downloads\2026 AS보고서 D테크",
        r"C:\Users\genoray1\Downloads\2026 AS보고서 K테크",
        r"C:\Users\genoray1\Downloads\2026 AS 보고서 부산",
        r"C:\Users\genoray1\Downloads\2026 AS보고서  M테크",
    ] for f in glob.glob(os.path.join(fo, "*.xlsx"))],
    "월간": [f for f in
             glob.glob(r"C:\Users\genoray1\Desktop\*.xlsx") +
             glob.glob(r"C:\Users\genoray1\Desktop\정명완 대리\05. 월간보고\*.xlsx")
             if ("월간" in os.path.basename(f))],
}
for label, files in groups.items():
    files = sorted(set(files))
    print(f"\n=== {label}: {len(files)} files ===", flush=True)
    ok = fail = 0
    t0 = time.time()
    for i, f in enumerate(files, 1):
        name = os.path.basename(f)
        try:
            with open(f, "rb") as fh:
                r = requests.post(f"{API}/api/ingest", files={"file": (name, fh)}, timeout=120)
            if r.status_code == 200:
                j = r.json()
                print(f"[{i:2}/{len(files)}] {j['format']:10} {j['period_label']:16} "
                      f"rows={sum(j['inserted'].values()):5} w{len(j['warnings'])}  {name[:40]}", flush=True)
                ok += 1
            else:
                print(f"[{i:2}] HTTP{r.status_code} {name}: {r.text[:120]}", flush=True)
                fail += 1
        except Exception as e:
            print(f"[{i:2}] ERR {name}: {e}", flush=True)
            fail += 1
    print(f"--- {label} done {time.time()-t0:.0f}s ok={ok} fail={fail}", flush=True)
print("\nALL DONE", flush=True)
