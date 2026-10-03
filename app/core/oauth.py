"""공통 OAuth 2.0 흐름 (사용자 동의 방식).

- 등록된 서비스들의 `scopes.py`를 provider별로 모아 한 번의 인가 요청으로 보낸다.
- `/auth/<provider>/login` → provider 동의 화면으로 리다이렉트
- `/auth/<provider>/callback` → code를 토큰으로 교환해 token_store에 저장
- `get_access_token(provider)` → 만료됐으면 refresh 후 access token 반환 (라우터가 쓰는 의존성)

Google 주의 (docs/google_drive.md 2절):
- refresh token은 첫 동의 때만 발급 → `access_type=offline&prompt=consent`
- 테스트 상태 + 외부 사용자 유형 앱의 refresh token은 7일 후 만료. 재로그인이 필요한 것을 오류로 착각하지 않는다.
- scope 추가 시 `include_granted_scopes=true`로 증분 인가. 서비스가 늘면 사용자가 재동의해야 한다.
"""

import secrets
from dataclasses import dataclass, field
from types import ModuleType
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.core.config import Settings, get_settings
from app.core.token_store import TokenSet, TokenStore
from app.services.google_docs import scopes as google_docs_scopes
from app.services.google_drive import scopes as google_drive_scopes
from app.services.google_sheets import scopes as google_sheets_scopes
from app.services.google_slides import scopes as google_slides_scopes

# 서비스가 추가되면 여기에 scopes 모듈만 추가한다.
REGISTERED_SCOPE_MODULES: list[ModuleType] = [
    google_drive_scopes,
    google_docs_scopes,
    google_slides_scopes,
    google_sheets_scopes,
]


@dataclass
class ProviderConfig:
    name: str
    authorize_url: str
    token_url: str
    revoke_url: str | None = None
    extra_authorize_params: dict[str, str] = field(default_factory=dict)
    # Zoom은 client_id:client_secret을 Basic 헤더로 보내고, Google은 본문에 넣는다.
    client_auth_in_header: bool = False


PROVIDERS: dict[str, ProviderConfig] = {
    "google": ProviderConfig(
        name="google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        revoke_url="https://oauth2.googleapis.com/revoke",
        extra_authorize_params={
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        },
    ),
    "zoom": ProviderConfig(
        name="zoom",
        authorize_url="https://zoom.us/oauth/authorize",
        token_url="https://zoom.us/oauth/token",
        revoke_url="https://zoom.us/oauth/revoke",
        client_auth_in_header=True,
    ),
}


def collect_scopes(provider: str) -> dict[str, str]:
    """provider에 속한 모든 서비스의 scope를 {scope: 사용 이유}로 합친다. 중복은 하나로."""
    merged: dict[str, str] = {}
    for module in REGISTERED_SCOPE_MODULES:
        if getattr(module, "PROVIDER", None) != provider:
            continue
        for scope, reason in module.SCOPES.items():
            merged.setdefault(scope, reason)
    return merged


def _client_credentials(provider: str, settings: Settings) -> tuple[str, str]:
    client_id = getattr(settings, f"{provider}_client_id")
    client_secret = getattr(settings, f"{provider}_client_secret")
    if not client_id or not client_secret:
        raise HTTPException(500, f"{provider.upper()}_CLIENT_ID / _CLIENT_SECRET 이 .env에 없습니다")
    return client_id, client_secret


def _provider(provider: str) -> ProviderConfig:
    if provider not in PROVIDERS:
        raise HTTPException(404, f"unknown provider: {provider}")
    return PROVIDERS[provider]


def get_token_store(settings: Settings = Depends(get_settings)) -> TokenStore:
    return TokenStore(settings.token_store_path)


def build_authorize_url(provider: str, settings: Settings, state: str) -> str:
    cfg = _provider(provider)
    client_id, _ = _client_credentials(provider, settings)
    params = {
        "client_id": client_id,
        "redirect_uri": settings.redirect_uri(provider),
        "response_type": "code",
        "scope": " ".join(collect_scopes(provider)),
        "state": state,
        **cfg.extra_authorize_params,
    }
    return f"{cfg.authorize_url}?{urlencode(params)}"


async def _post_token(provider: str, settings: Settings, data: dict[str, str]) -> dict:
    cfg = _provider(provider)
    client_id, client_secret = _client_credentials(provider, settings)
    auth = None
    if cfg.client_auth_in_header:
        auth = (client_id, client_secret)
    else:
        data = {**data, "client_id": client_id, "client_secret": client_secret}
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.post(cfg.token_url, data=data, auth=auth)
    if resp.status_code >= 400:
        # 토큰 응답 본문은 시크릿을 포함하지 않으므로 그대로 노출해도 된다 (에러 형태 기록용)
        raise HTTPException(resp.status_code, {"provider": provider, "token_error": resp.json()})
    return resp.json()


async def exchange_code(provider: str, code: str, settings: Settings) -> TokenSet:
    data = await _post_token(
        provider,
        settings,
        {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.redirect_uri(provider)},
    )
    return TokenSet.from_token_response(provider, data)


async def refresh(provider: str, current: TokenSet, settings: Settings) -> TokenSet:
    if not current.refresh_token:
        raise HTTPException(401, f"{provider}: refresh token이 없습니다. /auth/{provider}/login 으로 다시 로그인하세요")
    data = await _post_token(
        provider,
        settings,
        {"grant_type": "refresh_token", "refresh_token": current.refresh_token},
    )
    return TokenSet.from_token_response(provider, data, previous_refresh_token=current.refresh_token)


async def get_valid_token(provider: str, store: TokenStore, settings: Settings) -> TokenSet:
    token = store.get(provider)
    if token is None:
        raise HTTPException(401, f"{provider}: 저장된 토큰이 없습니다. /auth/{provider}/login 으로 로그인하세요")
    if token.is_expired():
        token = await refresh(provider, token, settings)
        store.save(token)  # Zoom은 이전 refresh token이 즉시 무효가 되므로 바로 저장
    return token


def access_token_dependency(provider: str):
    """라우터에서 `token: str = Depends(access_token_dependency("google"))` 로 쓴다."""

    async def _dep(
        store: TokenStore = Depends(get_token_store),
        settings: Settings = Depends(get_settings),
    ) -> str:
        return (await get_valid_token(provider, store, settings)).access_token

    return _dep


router = APIRouter(prefix="/auth", tags=["auth"])

# 테스트용 단일 사용자 흐름이라 state를 메모리에 둔다. 서비스 레포에서는 세션/DB로 옮긴다.
_pending_states: set[str] = set()


@router.get("/{provider}/login")
async def login(provider: str, settings: Settings = Depends(get_settings)):
    state = secrets.token_urlsafe(16)
    _pending_states.add(state)
    return RedirectResponse(build_authorize_url(provider, settings, state))


@router.get("/{provider}/callback")
async def callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    store: TokenStore = Depends(get_token_store),
):
    if error:
        raise HTTPException(400, {"provider": provider, "error": error})
    if state not in _pending_states:
        raise HTTPException(400, "state 불일치. /auth/{provider}/login 부터 다시 시작하세요")
    _pending_states.discard(state)
    if not code:
        raise HTTPException(400, "code 없음")

    token = await exchange_code(provider, code, settings)
    store.save(token)
    requested = set(collect_scopes(provider))
    return {
        "provider": provider,
        "expires_at": token.expires_at,
        "has_refresh_token": token.refresh_token is not None,
        "granted_scopes": token.scope,
        "missing_scopes": sorted(requested - set(token.scope)),  # 사용자가 동의 화면에서 뺀 scope
    }


@router.get("/{provider}/status")
async def status(provider: str, store: TokenStore = Depends(get_token_store)):
    token = store.get(provider)
    if token is None:
        return {"provider": provider, "logged_in": False}
    return {
        "provider": provider,
        "logged_in": True,
        "expired": token.is_expired(),
        "expires_at": token.expires_at,
        "obtained_at": token.obtained_at,
        "has_refresh_token": token.refresh_token is not None,
        "granted_scopes": token.scope,
    }


@router.post("/{provider}/refresh")
async def force_refresh(
    provider: str,
    settings: Settings = Depends(get_settings),
    store: TokenStore = Depends(get_token_store),
):
    """3단계 검증용: 만료를 기다리지 않고 refresh를 한 번 실제로 돌려본다."""
    current = store.get(provider)
    if current is None:
        raise HTTPException(401, f"{provider}: 저장된 토큰이 없습니다")
    token = await refresh(provider, current, settings)
    store.save(token)
    return {"provider": provider, "expires_at": token.expires_at, "refresh_token_rotated": token.refresh_token != current.refresh_token}


@router.get("/{provider}/scopes")
async def scopes(provider: str):
    """이 provider에 요청할 scope와 각 사용 이유 (심사 제출 자료의 재료)."""
    _provider(provider)
    return collect_scopes(provider)
