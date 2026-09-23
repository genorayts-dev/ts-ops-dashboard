"""
geno-one(사내 ERP, one.genoray.com) AS관리(/aspart) 데이터 자동 수집.

로그인 폼 구조(2026-09-17 직접 확인):
    GET  https://one.genoray.com/login   -> 로그인 폼 (CodeIgniter, CSRF 토큰 포함)
    POST https://one.genoray.com/login
        csrf_test_name = <로그인 폼 hidden input 값, 매 세션/요청마다 갱신됨>
        url            = <로그인 폼 hidden input 값(리다이렉트 대상), 그대로 되돌려보냄>
        mem_userid     = 아이디
        mem_password   = 비밀번호

계정: .env 의 TSD_GENO_ONE_USERNAME / TSD_GENO_ONE_PASSWORD (서버측 파일에만 저장,
      코드/채팅에 값 직접 기재 금지).

AS관리 export(2026-09-17 확인 완료): `/aspart` 목록 페이지의 `<a href="/aspart/excel_download/?" download>`
링크는 쿼리 파라미터가 없고, 별도 JS 핸들러도 없음 — 서버가 현재 세션의 목록 필터 상태를
그대로 반영해 내려줌. 로그인 세션으로 `/aspart` 를 한 번 방문(기본 필터 진입) 후
`/aspart/excel_download/` 를 GET 하면 `as_list_YYYYMMDD.xlsx` (헤더 제외 720행, 40컬럼,
해외(M/D)만·K국내 0건 — 기존 통합시트 md_service 1,190건과 스코프 다름, 별도 테이블로
격리 적재 후 교차검증 필요)를 받는다.
"""
from __future__ import annotations

import re

from .config import settings

BASE = "https://one.genoray.com"
_CSRF_RE = re.compile(r'name=["\']csrf_test_name["\']\s+value=["\']([^"\']+)["\']')
_URL_RE = re.compile(r'name=["\']url["\']\s+value=["\']([^"\']*)["\']')


def enabled() -> bool:
    return bool(settings.geno_one_username and settings.geno_one_password)


def login():
    """로그인된 requests.Session 반환. 실패 시 RuntimeError."""
    if not enabled():
        raise RuntimeError("geno-one 계정이 설정되지 않았습니다 (TSD_GENO_ONE_USERNAME/PASSWORD).")
    import requests

    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (ts-ops-dashboard sync bot)"

    r = s.get(f"{BASE}/login", timeout=30)
    r.raise_for_status()
    m_csrf = _CSRF_RE.search(r.text)
    if not m_csrf:
        raise RuntimeError("로그인 폼에서 csrf_test_name 을 찾지 못했습니다 (페이지 구조 변경?).")
    m_url = _URL_RE.search(r.text)

    payload = {
        "csrf_test_name": m_csrf.group(1),
        "url": m_url.group(1) if m_url else "",
        "mem_userid": settings.geno_one_username,
        "mem_password": settings.geno_one_password,
    }
    r2 = s.post(f"{BASE}/login", data=payload, timeout=30, allow_redirects=True)
    r2.raise_for_status()
    if "mem_password" in r2.text or "csrf_test_name" in r2.text:
        # 로그인 폼이 다시 나타나면 실패(아이디/비번 오류 또는 CSRF 불일치)
        raise RuntimeError("geno-one 로그인 실패 — 계정 정보 또는 CSRF 토큰을 확인하세요.")
    return s


def inspect_aspart_page() -> str:
    """로그인 후 /aspart 페이지 원본 HTML 반환 — 다운로드 링크의 정확한
    쿼리 파라미터를 확정하기 위한 1회성 조사용. 자동화 파이프라인에는 쓰지 않음."""
    s = login()
    r = s.get(f"{BASE}/aspart", timeout=30)
    r.raise_for_status()
    return r.text


def fetch_aspart_xlsx() -> bytes:
    """AS관리(/aspart) export xlsx 바이트 반환."""
    s = login()
    s.get(f"{BASE}/aspart", timeout=30)  # 목록 페이지 방문 → 서버측 기본 필터 상태 진입
    r = s.get(f"{BASE}/aspart/excel_download/", timeout=60)
    r.raise_for_status()
    ct = r.headers.get("Content-Type", "")
    if "spreadsheetml" not in ct and r.content[:2] != b"PK":
        raise RuntimeError(f"예상과 다른 응답(xlsx 아님, Content-Type={ct}) — URL/파라미터 재확인 필요.")
    return r.content
