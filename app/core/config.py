"""`.env` 로드. 시크릿은 전부 여기로만 들어온다."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_base_url: str = "http://localhost:8000"

    google_client_id: str = ""
    google_client_secret: str = ""

    zoom_client_id: str = ""
    zoom_client_secret: str = ""

    token_store_path: Path = Path(".tokens/tokens.json")

    def redirect_uri(self, provider: str) -> str:
        return f"{self.app_base_url}/auth/{provider}/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
