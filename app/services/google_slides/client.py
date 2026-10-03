"""Google Slides REST 호출만 (presentations.create / get / batchUpdate). Drive 호출은 google_drive/client.py에.

함정 (docs/google_slides.md 10절):
- `presentations.create`는 title·pageSize·locale 외 모든 필드를 무시한다. 폴더 지정은 Drive로.
- 편집 대상은 문자 인덱스가 아니라 objectId. 템플릿 치환은 ID 대신 텍스트 태그(`replaceAllText`)로 한다.
- 텍스트를 바꾸는 요청이 들어가면 그 도형의 autofit이 NONE으로 꺼진다. 긴 치환 텍스트는 넘친다.
"""

import httpx

BASE_URL = "https://slides.googleapis.com/v1"


class SlidesApiError(Exception):
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body
        err = body.get("error", {}) if isinstance(body, dict) else {}
        self.message: str = err.get("message", str(body))
        self.status_text: str | None = err.get("status")  # 예: INVALID_ARGUMENT, NOT_FOUND, RESOURCE_EXHAUSTED
        super().__init__(f"Slides {status} {self.status_text}: {self.message}")

    @property
    def is_rate_limit(self) -> bool:
        return self.status == 429 or self.status_text == "RESOURCE_EXHAUSTED"


class SlidesClient:
    def __init__(self, access_token: str, http: httpx.AsyncClient | None = None):
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._http = http or httpx.AsyncClient(timeout=30)

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        resp = await self._http.request(method, url, headers=self._headers, **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = {"error": {"message": resp.text}}
            raise SlidesApiError(resp.status_code, body)
        return resp.json()

    async def create(self, title: str) -> dict:
        """presentations.create (쓰기 쿼터). 빈 프레젠테이션(제목 슬라이드 1장). 응답에 presentationId·slides·layouts가 온다."""
        return await self._request("POST", f"{BASE_URL}/presentations", json={"title": title})

    async def get(self, presentation_id: str, fields: str | None = None) -> dict:
        """presentations.get (읽기 쿼터). 마스터·레이아웃까지 와서 크다. 필요한 것만 받으려면 fields 마스크."""
        params = {"fields": fields} if fields else None
        return await self._request("GET", f"{BASE_URL}/presentations/{presentation_id}", params=params)

    async def batch_update(self, presentation_id: str, requests: list[dict], required_revision_id: str | None = None) -> dict:
        """presentations.batchUpdate (쓰기 쿼터 1회, 안의 요청 수 무관). requests 전체가 원자적으로 적용된다.

        replies[]는 requests와 1:1. required_revision_id를 주면 그 사이 다른 편집이 있었을 때 실패한다.
        """
        body: dict = {"requests": requests}
        if required_revision_id:
            body["writeControl"] = {"requiredRevisionId": required_revision_id}
        return await self._request("POST", f"{BASE_URL}/presentations/{presentation_id}:batchUpdate", json=body)
