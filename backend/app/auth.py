from fastapi import Request

from .config import settings


def current_user(request: Request) -> str:
    """
    사내 리버스 프록시(SSO/AD)가 인증 후 넣어주는 헤더에서 사용자 식별.
    프록시가 없는 개발 환경에서는 settings.dev_user.
    운영에서는 프록시가 이 헤더를 '항상' 덮어쓰도록(클라이언트 위조 방지) 설정할 것.
    """
    return request.headers.get(settings.auth_header) or settings.dev_user
