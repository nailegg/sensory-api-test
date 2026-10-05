"""`.env` 로드. 시크릿은 전부 여기로만 들어온다."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_base_url: str = "http://localhost:8000"

    google_client_id: str = ""
    google_client_secret: str = ""
    # Google Picker (교수자가 Drive에 이미 가진 파일을 템플릿으로 고르는 테스트 페이지, GET /google/picker). docs/google_drive.md 2.1절
    # API 키: 콘솔 > 사용자 인증 정보 > API 키. Picker API 사용 설정 필요. 서버는 쓰지 않고 브라우저 JS(setDeveloperKey)에만 넘긴다.
    google_picker_api_key: str = ""
    # setAppId에 넣는 Cloud 프로젝트 "번호"(ID가 아님). 비우면 클라이언트 ID 앞의 숫자(같은 프로젝트 번호)를 쓴다.
    google_project_number: str = ""

    zoom_client_id: str = ""
    zoom_client_secret: str = ""
    # Zoom 리다이렉트 URL은 https 공개 주소여야 한다(ngrok 고정 도메인). redirect_uri("zoom")가 쓴다. docs/zoom.md 2절
    zoom_public_base_url: str = ""
    zoom_webhook_secret_token: str = ""

    token_store_path: Path = Path(".tokens/tokens.json")

    def redirect_uri(self, provider: str) -> str:
        base = self.app_base_url
        if provider == "zoom":
            if not self.zoom_public_base_url:
                raise ValueError("ZOOM_PUBLIC_BASE_URL(ngrok https 주소)이 .env에 없습니다")
            base = self.zoom_public_base_url.rstrip("/")
        return f"{base}/auth/{provider}/callback"

    def picker_app_id(self) -> str:
        """Picker setAppId 값 = Cloud 프로젝트 번호. 웹 클라이언트 ID는 `<프로젝트 번호>-xxxx.apps.googleusercontent.com` 꼴이라
        GOOGLE_PROJECT_NUMBER가 비어 있으면 거기서 꺼낸다(2026-10-04 실측 클라이언트 ID로 확인). 다르면 .env에 명시한다."""
        if self.google_project_number:
            return self.google_project_number
        head = self.google_client_id.split("-", 1)[0]
        return head if head.isdigit() else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
