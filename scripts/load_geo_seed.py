"""geo_place 마스터 시드 적재. 사용: python scripts/load_geo_seed.py [csv경로]"""
import csv
import sys

from sqlalchemy import create_engine, text

DB = "postgresql+psycopg://tsd:tsd@localhost:5432/tsd"
CSV = sys.argv[1] if len(sys.argv) > 1 else "data/geo_place_seed.csv"

engine = create_engine(DB, future=True)
with engine.begin() as cx, open(CSV, encoding="utf-8") as fh:
    n = 0
    for row in csv.DictReader(fh):
        cx.execute(text("""
            INSERT INTO geo_place(name_ko, canonical, kind, iso3, region_group, lat, lng)
            VALUES (:name_ko, :canonical, :kind, :iso3, :region_group, :lat, :lng)
            ON CONFLICT (name_ko, kind) DO UPDATE SET
                canonical = EXCLUDED.canonical, iso3 = EXCLUDED.iso3,
                region_group = EXCLUDED.region_group, lat = EXCLUDED.lat, lng = EXCLUDED.lng
        """), row)
        n += 1
    print(f"{n} rows upserted from {CSV}")
