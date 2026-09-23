"""
구글 시트 연동.

읽기: 링크 공유(누구나 보기)된 시트는 인증 없이 xlsx export 로 가져온다 →
      기존 parse()/persist() 파이프라인에 그대로 태운다(시트 구조를 따로 해석할
      필요 없이 엑셀 업로드와 동일하게 처리). 비공개 시트는 서비스 계정(선택,
      TSD_GOOGLE_SA_JSON)으로 폴백.

쓰기(append_rows): 회사 Google 계정이 결제수단 등록 제한으로 GCP 서비스 계정을
      만들 수 없어(2026-09-21) **Google Apps Script 웹 앱**으로 대신한다 — 시트
      편집자가 `deploy/apps_script_append.gs` 를 그 시트에 붙여넣고 웹 앱으로
      배포하면 Cloud 프로젝트/서비스 계정/결제수단 전혀 없이 끝난다(배포 방법은
      그 파일 상단 주석 참고). 백엔드는 그 웹 앱 URL 에 비밀키를 실어 POST 만 한다.
"""
from __future__ import annotations

import io
import re

from .config import settings

_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def enabled() -> bool:
    # 서비스 계정이 없어도 '링크 공유(누구나 보기)' 시트는 공개 export 로 가져올 수 있음
    return True


def extract_id(url_or_id: str) -> str:
    m = _ID_RE.search(url_or_id or "")
    if m:
        return m.group(1)
    return (url_or_id or "").strip()


def _service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        settings.google_sa_json, scopes=_SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _fetch_public(sheet_id: str) -> bytes | None:
    """링크 공유된 시트는 인증 없이 xlsx export 가능."""
    import urllib.request

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            ct = r.headers.get("Content-Type", "")
            data = r.read()
        if "spreadsheetml" in ct or data[:2] == b"PK":
            return data
    except Exception:
        pass
    return None


def can_write() -> bool:
    return bool(settings.geno_one_sheet_webhook_url and settings.geno_one_sheet_secret)


def append_rows(rows: list[list], *, tab: str | None = None, tab_needles: list[str] | None = None) -> dict:
    """Apps Script 웹 앱에 POST 해서 탭 맨 끝에 행을 추가한다.

    `tab_needles` 를 쓰면(권장) Apps Script 가 호출 시점에 실시간으로 탭 이름을
    찾는다 — 외부 자동화 스크립트가 탭 이름을 수시로 바꾸는 데다, 우리 쪽 xlsx
    export 는 캐시돼 있어 미리 계산해둔 정확한 이름(`tab`)이 이미 stale 할 수
    있기 때문(2026-09-21, 'MD AS' → '[M/D] AS' 로 바뀌어 겪음)."""
    if not can_write():
        raise RuntimeError(
            "쓰기 권한 없음 — TSD_GENO_ONE_SHEET_WEBHOOK_URL/TSD_GENO_ONE_SHEET_SECRET 설정 필요 "
            "(deploy/apps_script_append.gs 를 시트에 배포)."
        )
    import requests

    payload = {"secret": settings.geno_one_sheet_secret, "rows": rows}
    payload.update({"tab_needles": tab_needles} if tab_needles else {"tab": tab})
    r = requests.post(settings.geno_one_sheet_webhook_url, json=payload, timeout=60)
    r.raise_for_status()
    res = r.json()
    if not res.get("ok"):
        extra = f" (실제 탭 목록: {res['available_tabs']})" if res.get("available_tabs") else ""
        raise RuntimeError(f"Apps Script 응답 오류: {res.get('error')}{extra}")
    return res


def fetch_xlsx(sheet_id: str) -> tuple[bytes, str]:
    """스프레드시트를 xlsx 바이트로 export. (bytes, 파일명) 반환."""
    pub = _fetch_public(sheet_id)
    if pub is not None:
        return pub, f"gsheet_{sheet_id[:8]}.xlsx"

    if not settings.google_sa_json:
        raise RuntimeError(
            "시트를 공개 export 할 수 없습니다. 링크 공유(누구나 보기)로 바꾸거나 "
            "서비스 계정(TSD_GOOGLE_SA_JSON)을 설정하세요."
        )
    from googleapiclient.http import MediaIoBaseDownload

    drv = _service()
    meta = drv.files().get(fileId=sheet_id, fields="name", supportsAllDrives=True).execute()
    name = meta.get("name", sheet_id)
    req = drv.files().export_media(fileId=sheet_id, mimeType=_XLSX_MIME)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _status, done = dl.next_chunk()
    return buf.getvalue(), f"{name}.xlsx"
