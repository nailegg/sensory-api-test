"""Google Docs REST 호출만 (documents.create / get / batchUpdate). Drive 호출은 google_drive/client.py에.

함정 (docs/google_docs.md 10절):
- `documents.create`는 title 외 모든 필드를 무시한다. 폴더 지정은 Drive로.
- `documents.get`은 `includeTabsContent=true` 없이는 첫 탭 내용만 돌려준다.
- batchUpdate 인덱스는 UTF-16 코드 단위. 삽입할수록 뒤 인덱스가 밀리므로 뒤에서 앞으로 수정한다.
"""

import httpx

BASE_URL = "https://docs.googleapis.com/v1"


class DocsApiError(Exception):
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body
        err = body.get("error", {}) if isinstance(body, dict) else {}
        self.message: str = err.get("message", str(body))
        self.status_text: str | None = err.get("status")  # 예: INVALID_ARGUMENT, NOT_FOUND, RESOURCE_EXHAUSTED
        super().__init__(f"Docs {status} {self.status_text}: {self.message}")

    @property
    def is_rate_limit(self) -> bool:
        return self.status == 429 or self.status_text == "RESOURCE_EXHAUSTED"


class DocsClient:
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
            raise DocsApiError(resp.status_code, body)
        return resp.json()

    async def create(self, title: str) -> dict:
        """documents.create (쓰기 쿼터). 빈 문서. 응답에 documentId와 빈 body 구조가 온다."""
        return await self._request("POST", f"{BASE_URL}/documents", json={"title": title})

    async def get(self, document_id: str, include_tabs_content: bool = True) -> dict:
        """documents.get (읽기 쿼터)."""
        params = {"includeTabsContent": str(include_tabs_content).lower()}
        return await self._request("GET", f"{BASE_URL}/documents/{document_id}", params=params)

    async def batch_update(self, document_id: str, requests: list[dict], required_revision_id: str | None = None) -> dict:
        """documents.batchUpdate (쓰기 쿼터). requests 전체가 원자적으로 적용된다.

        required_revision_id를 주면 그 사이 다른 편집이 있었을 때 실패한다 (동시 편집 보호).
        """
        body: dict = {"requests": requests}
        if required_revision_id:
            body["writeControl"] = {"requiredRevisionId": required_revision_id}
        return await self._request("POST", f"{BASE_URL}/documents/{document_id}:batchUpdate", json=body)
