"""
geno-one(사내 ERP) AS관리 자동 동기화 + 통합시트 반영 스케줄러.

매일 정해진 시각에 백그라운드로 순서대로 실행:
  1) `routers/geno_one.py` 의 POST /api/geno_one/sync 와 동일한 파이프라인
     (로그인 → export → 파싱 → persist) — 계정 미설정 시 조용히 스킵.
  2) `ingest/geno_one_reconcile.py` 의 `apply()` — geno_one_ticket 중 통합시트에
     없는 완료(Close) 티켓을 'MD AS' 탭에 추가 + 재동기화. Apps Script 웹앱
     미설정(TSD_GENO_ONE_SHEET_WEBHOOK_URL/SECRET) 시 조용히 스킵.
2단계가 실패해도 1단계(동기화 자체)는 이미 끝난 뒤라 서로 독립적으로 로그만 남긴다.

시각 변경: DAILY_HOUR/DAILY_MINUTE 만 바꾸면 됨(기본 매일 07:00 KST — 업무
시작 전에 최신 데이터가 반영되도록). pytz 사용 — slim 이미지에 시스템
tzdata 가 없어도 동작(pytz 는 자체 시간대 데이터를 포함).
"""
from __future__ import annotations

import logging

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import geno_one, gsheet
from .db import SessionLocal
from .ingest.geno_one_aspart import parse_geno_one_aspart
from .ingest.geno_one_reconcile import apply as reconcile_apply
from .ingest.persist import persist

log = logging.getLogger("scheduler")

DAILY_HOUR = 7
DAILY_MINUTE = 0

_scheduler: BackgroundScheduler | None = None


def _sync_geno_one_job() -> None:
    if not geno_one.enabled():
        log.info("geno-one 자동 동기화 스킵 — 계정 미설정(TSD_GENO_ONE_USERNAME/PASSWORD)")
        return
    db = SessionLocal()
    try:
        raw = geno_one.fetch_aspart_xlsx()
        parsed = parse_geno_one_aspart(raw, "geno_one_aspart.xlsx")
        res = persist(db, parsed, filename="geno_one_aspart.xlsx", raw=raw, user="geno_one:scheduler")
        db.commit()
        log.info("geno-one 자동 동기화 완료: %s", res)
    except Exception:
        db.rollback()
        log.exception("geno-one 자동 동기화 실패")
    finally:
        db.close()

    if not gsheet.can_write():
        log.info("geno-one 통합시트 반영 스킵 — Apps Script 웹앱 미설정")
        return
    db = SessionLocal()
    try:
        res = reconcile_apply(db, only_closed=True)
        db.commit()
        log.info("geno-one 통합시트 반영 완료: %s", res)
    except Exception:
        db.rollback()
        log.exception("geno-one 통합시트 반영 실패")
    finally:
        db.close()


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    kst = pytz.timezone("Asia/Seoul")
    _scheduler = BackgroundScheduler(timezone=kst)
    _scheduler.add_job(
        _sync_geno_one_job,
        # CronTrigger 는 timezone 을 명시하지 않으면 스케줄러 시간대를 물려받지 않고
        # UTC 로 고정되므로(APScheduler 3.x 동작), 반드시 여기서 직접 지정한다.
        CronTrigger(hour=DAILY_HOUR, minute=DAILY_MINUTE, timezone=kst),
        id="geno_one_daily_sync",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    log.info(
        "스케줄러 시작 — geno-one 자동 동기화+통합시트 반영 매일 %02d:%02d(KST)",
        DAILY_HOUR, DAILY_MINUTE,
    )


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
