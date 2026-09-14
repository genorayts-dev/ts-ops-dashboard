# -*- coding: utf-8 -*-
"""현재까지 적재된 데이터로 대시보드 집계 미리보기."""
import io
import sys

import psycopg

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
cx = psycopg.connect("host=localhost port=5432 dbname=tsd user=tsd password=tsd")


def q(sql):
    with cx.cursor() as c:
        c.execute(sql)
        return c.fetchall()


print("=" * 70)
print("적재 현황")
for r in q("""SELECT ptype, count(DISTINCT period_id) periods, count(*) batches
              FROM upload_batch b JOIN report_period p ON p.id=b.period_id
              WHERE b.status='active' GROUP BY ptype ORDER BY ptype"""):
    print(f"  {r[0]:10} 기간 {r[1]:3}  배치 {r[2]:3}")

print("\n" + "=" * 70)
print("주간 최신주 팀별 실적 (latest weekly)")
for r in q("""
    SELECT s.team_code, s.received, s.inbound, s.revenue_krw, s.revenue_krw_ytd
    FROM svc_summary s
    JOIN v_latest_batch lb ON lb.batch_id=s.batch_id
    JOIN report_period p ON p.id=s.period_id
    WHERE p.ptype='weekly'
      AND p.id=(SELECT id FROM report_period WHERE ptype='weekly'
                ORDER BY year DESC, month DESC, week_no DESC LIMIT 1)
    ORDER BY s.team_code"""):
    print(f"  {r[0]}테크  접수 {r[1] or 0:4}  Inbound {r[2] or 0:5}  "
          f"당주매출 {(r[3] or 0):>12,}  누계 {(r[4] or 0):>15,}")

print("\n" + "=" * 70)
print("월별 AS매출 추이 (monthly_trend, 원)")
rows = q("""SELECT month, team_code, SUM(revenue_krw)::bigint
           FROM monthly_trend mt JOIN v_latest_batch lb ON lb.batch_id=mt.batch_id
           WHERE year=2026 GROUP BY month, team_code ORDER BY month, team_code""")
bym = {}
for m, t, v in rows:
    bym.setdefault(m, {})[t] = v
for m, d in sorted(bym.items()):
    print(f"  {m:2}월  " + "  ".join(f"{t}:{(d.get(t) or 0):>12,}" for t in ("D", "M", "K")))

print("\n" + "=" * 70)
print("AS 티켓 — 팀·장비군별 건수 / 유상 수리매출(원환산)")
for r in q("""
    SELECT org, product_line, count(*) n,
           sum(CASE WHEN warranty='유상' THEN 1 ELSE 0 END) paid_n,
           sum(coalesce(repair_amount_krw,0))::bigint krw
    FROM as_ticket t JOIN v_latest_batch lb ON lb.batch_id=t.batch_id
    GROUP BY org, product_line ORDER BY org, product_line"""):
    print(f"  {r[0]:4} {r[1] or '-':16} 건수 {r[2]:5}  유상 {r[3]:4}  수리매출 {r[4]:>14,}")

print("\n" + "=" * 70)
print("해외 AS 국가 TOP 15 (지도 탭 ①)")
for r in q("""
    SELECT coalesce(g.canonical, t.country) country, g.iso3, count(*) n
    FROM as_ticket t
    JOIN v_latest_batch lb ON lb.batch_id=t.batch_id
    LEFT JOIN geo_place g ON g.name_ko=t.country AND g.kind='country'
    WHERE t.is_overseas GROUP BY 1, g.iso3 ORDER BY n DESC LIMIT 15"""):
    print(f"  {r[0] or '(미상)':12} {r[1] or '???':4}  {r[2]:5}")

print("\n" + "=" * 70)
print("고장 시정조치 구분 (fix_class) 분포")
for r in q("""
    SELECT coalesce(fix_class,'(미상)') fc, count(*) n
    FROM as_ticket t JOIN v_latest_batch lb ON lb.batch_id=t.batch_id
    GROUP BY 1 ORDER BY n DESC"""):
    print(f"  {r[0]:8} {r[1]:6}")

print("\n" + "=" * 70)
print("보증 무상/유상 비율")
for r in q("""
    SELECT coalesce(warranty,'(미상)') w, count(*) n,
           round(100.0*count(*)/sum(count(*)) over (),1) pct
    FROM as_ticket t JOIN v_latest_batch lb ON lb.batch_id=t.batch_id
    GROUP BY 1 ORDER BY n DESC"""):
    print(f"  {r[0]:8} {r[1]:6}  {r[2]}%")

print("\n" + "=" * 70)
print("반복 AS 장비 TOP 10 (같은 제조번호 다건)")
for r in q("""
    SELECT serial_no, max(product_model), count(*) n
    FROM as_ticket t JOIN v_latest_batch lb ON lb.batch_id=t.batch_id
    WHERE serial_no IS NOT NULL AND serial_no <> ''
    GROUP BY serial_no HAVING count(*) >= 3 ORDER BY n DESC LIMIT 10"""):
    print(f"  {r[0]:24} {r[1] or '':20} {r[2]}회")

cx.close()
