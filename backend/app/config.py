from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TSD_")

    database_url: str = "postgresql+psycopg://tsd:tsd@localhost:5432/tsd"

    # 리버스 프록시(사내 SSO)가 넣어주는 사용자 식별 헤더.
    # 프록시가 없으면 dev_user 로 대체.
    auth_header: str = "X-Remote-User"
    dev_user: str = "dev"

    # 프런트 개발 서버 CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    parser_version: str = "2026.09.1"

    # 국내 상세 지도 타일 URL 템플릿 (사용자가 새로 발급한 키 포함).
    # 예: https://api.maptiler.com/maps/streets-v2/{z}/{x}/{y}.png?key=XX: 프런트로 그대로 전달.
    kr_map_tile_url: str = ""
    kr_map_attribution: str = ""

    # 구글 시트 연동: 서비스 계정 JSON 키 파일 경로 (컨테이너 내부 경로).
    # 비어 있으면 /api/gsheet/* 는 501 을 반환.
    google_sa_json: str = ""


settings = Settings()
