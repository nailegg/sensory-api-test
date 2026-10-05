"""Zoom REST 호출만 (users/me, meetings 생성·조회·수정·삭제). docs/zoom.md 4.1절.

함정 (docs/zoom.md 10절):
- 미팅 생성·수정은 사용자당 하루 100회(UTC). 삭제 포함 여부는 미확인.
- `DELETE /meetings/{id}`에 `occurrence_id`가 없으면 반복 미팅 시리즈 전체가 지워진다.
- `start_url`은 2시간 만료 + 호스트 권한. 저장하지 말고 필요할 때 `get_meeting`으로 다시 받는다.
"""

import httpx

BASE_URL = "https://api.zoom.us/v2"


class ZoomApiError(Exception):
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body
        self.code: int | None = body.get("code") if isinstance(body, dict) else None  # 예: 124 토큰 무효, 3001 미팅 없음, 200 유료 전용
        self.message: str = body.get("message", str(body)) if isinstance(body, dict) else str(body)
        super().__init__(f"Zoom {status} code={self.code}: {self.message}")

    @property
    def is_rate_limit(self) -> bool:
        return self.status == 429


class ZoomClient:
    def __init__(self, access_token: str, http: httpx.AsyncClient | None = None, base_url: str = BASE_URL):
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._http = http or httpx.AsyncClient(timeout=30)
        self._base = base_url

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        resp = await self._http.request(method, f"{self._base}{path}", headers=self._headers, **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = {"message": resp.text}
            raise ZoomApiError(resp.status_code, body)
        return resp.json() if resp.content else {}  # PATCH·DELETE는 204 빈 본문

    async def get_me(self) -> dict:
        """GET /users/me (LIGHT). `type` 1 Basic · 2 Licensed."""
        return await self._request("GET", "/users/me")

    async def create_meeting(self, body: dict) -> dict:
        """POST /users/me/meetings (LIGHT, 하루 100회). 응답 201에 join_url·start_url·occurrences."""
        return await self._request("POST", "/users/me/meetings", json=body)

    async def get_meeting(self, meeting_id: str, occurrence_id: str | None = None) -> dict:
        """GET /meetings/{id} (LIGHT). status는 waiting/started뿐이다."""
        params = {"occurrence_id": occurrence_id} if occurrence_id else None
        return await self._request("GET", f"/meetings/{meeting_id}", params=params)

    async def update_meeting(self, meeting_id: str, body: dict, occurrence_id: str | None = None) -> None:
        """PATCH /meetings/{id} (LIGHT, 하루 100회에 포함). 204."""
        params = {"occurrence_id": occurrence_id} if occurrence_id else None
        await self._request("PATCH", f"/meetings/{meeting_id}", json=body, params=params)

    async def delete_meeting(self, meeting_id: str, occurrence_id: str | None = None) -> None:
        """DELETE /meetings/{id} (LIGHT). 204. occurrence_id가 없으면 반복 시리즈 전체."""
        params = {"occurrence_id": occurrence_id} if occurrence_id else None
        await self._request("DELETE", f"/meetings/{meeting_id}", params=params)
