"""
구글 시트 연동.

동작: 서비스 계정으로 Google Drive API 를 호출해 대상 스프레드시트를
      .xlsx 로 export → 기존 parse()/persist() 파이프라인에 그대로 태운다.
      (시트 구조를 따로 해석할 필요 없이 엑셀 업로드와 동일하게 처리)

준비물 (사용자가 생성):
  1. Google Cloud 프로젝트 → Drive API + Sheets API 사용 설정
  2. 서비스 계정 생성 → JSON 키 다운로드
  3. 연동할 각 구글 시트를 서비스 계정 이메일에 '뷰어' 로 공유
  4. JSON 키를 서버의 deploy/google-sa.json 에 두고
     docker-compose 의 TSD_GOOGLE_SA_JSON=/run/secrets/google-sa.json 로 마운트
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
