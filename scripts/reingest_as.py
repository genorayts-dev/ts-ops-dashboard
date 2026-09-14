"""AS 82개 파일만 재적재 (파서 개선: region_kr + K 고장코드)."""
import glob
import os
import time

import requests

API = "http://localhost:8080"   # nginx 경유 (Docker Desktop Windows 에서 :8000 직결이 불안정)
FOLDERS = [
    r"C:\Users\genoray1\Downloads\2026 AS보고서 D테크",
    r"C:\Users\genoray1\Downloads\2026 AS보고서 K테크",
    r"C:\Users\genoray1\Downloads\2026 AS 보고서 부산",
    r"C:\Users\genoray1\Downloads\2026 AS보고서  M테크",
]
files = sorted(f for fo in FOLDERS for f in glob.glob(os.path.join(fo, "*.xlsx")))
print(f"{len(files)} AS files", flush=True)
ok = fail = 0
t0 = time.time()
for i, f in enumerate(files, 1):
    name = os.path.basename(f)
    try:
        with open(f, "rb") as fh:
            r = requests.post(f"{API}/api/ingest", files={"file": (name, fh)}, timeout=180)
        j = r.json()
        if r.status_code == 200:
            print(f"[{i:2}/{len(files)}] {j['period_label']:16} rows={sum(j['inserted'].values()):4} "
                  f"warn={len(j['warnings'])}  {name[:44]}", flush=True)
            ok += 1
        else:
            print(f"[{i:2}] HTTP{r.status_code} {name} {r.text[:120]}", flush=True)
            fail += 1
    except Exception as e:
        print(f"[{i:2}] ERR {name}: {e}", flush=True)
        fail += 1
print(f"\ndone {time.time()-t0:.0f}s ok={ok} fail={fail}", flush=True)
