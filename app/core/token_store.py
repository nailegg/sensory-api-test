"""토큰 저장. 테스트 단계에서는 로컬 JSON 파일 하나에 provider별로 최신 토큰 한 벌만 둔다.

Google refresh token은 계정 × 클라이언트 ID당 100개까지라 항상 최신 것으로 덮어쓴다.
Zoom refresh token은 갱신할 때마다 새로 발급된다. 공식 문서가 최신 것만 쓰라고 하므로 갱신 직후 반드시 저장한다
(이전 것이 즉시 무효는 아니었다. 2026-10-05 실측, docs/zoom.md 2.2절).
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel


class TokenSet(BaseModel):
    provider: str
    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_at: datetime
    scope: list[str] = []  # 실제로 부여받은 scope. 사용자가 동의 화면에서 일부를 뺄 수 있다
    obtained_at: datetime

    def is_expired(self, leeway_seconds: int = 60) -> bool:
        return datetime.now(UTC) >= self.expires_at - timedelta(seconds=leeway_seconds)

    @classmethod
    def from_token_response(cls, provider: str, data: dict, previous_refresh_token: str | None = None) -> "TokenSet":
        """OAuth 토큰 응답(dict) → TokenSet.

        refresh 응답에 refresh_token이 없으면(Google) 이전 것을 유지한다.
        """
        now = datetime.now(UTC)
        scope_raw = data.get("scope", "")
        return cls(
            provider=provider,
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token") or previous_refresh_token,
            token_type=data.get("token_type", "Bearer"),
            expires_at=now + timedelta(seconds=int(data.get("expires_in", 3600))),
            scope=scope_raw.split() if isinstance(scope_raw, str) else list(scope_raw),
            obtained_at=now,
        )


class TokenStore:
    def __init__(self, path: Path):
        self.path = path

    def _read_all(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write_all(self, data: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, provider: str) -> TokenSet | None:
        raw = self._read_all().get(provider)
        return TokenSet.model_validate(raw) if raw else None

    def save(self, token: TokenSet) -> None:
        data = self._read_all()
        data[token.provider] = json.loads(token.model_dump_json())
        self._write_all(data)

    def delete(self, provider: str) -> None:
        data = self._read_all()
        data.pop(provider, None)
        self._write_all(data)
