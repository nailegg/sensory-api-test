"""Google Forms REST 호출만 (forms.create / get / batchUpdate / setPublishSettings, responses.list / get).
Drive 호출(폴더 이동, 응답자 권한, 복사, 휴지통)은 google_drive/client.py에.

함정 (docs/google_forms.md 10절):
- 2026-06-30 이후 API로 만든 폼은 미게시 상태로 생성된다. 응답을 받으려면 setPublishSettings로 게시한다.
- forms.create는 info.title·documentTitle 외 필드를 받지 않는다. 질문·설정은 batchUpdate로.
- 응답은 읽기 전용. 제출·수정·삭제 API가 없다.
- responses.list는 별도 "expensive read" 쿼터(사용자당 분당 180).
"""

import httpx

BASE_URL = "https://forms.googleapis.com/v1"


class FormsApiError(Exception):
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body
        err = body.get("error", {}) if isinstance(body, dict) else {}
        self.message: str = err.get("message", str(body))
        self.status_text: str | None = err.get("status")  # 예: INVALID_ARGUMENT, NOT_FOUND, FAILED_PRECONDITION
        super().__init__(f"Forms {status} {self.status_text}: {self.message}")

    @property
    def is_rate_limit(self) -> bool:
        return self.status == 429 or self.status_text == "RESOURCE_EXHAUSTED"


class FormsClient:
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
            raise FormsApiError(resp.status_code, body)
        return resp.json() if resp.content else {}

    # --- forms ---

    async def create(self, title: str, document_title: str | None = None, unpublished: bool | None = None) -> dict:
        """forms.create (쓰기 쿼터). 본문은 info.title(응답자에게 보이는 제목)과 info.documentTitle(Drive 파일명)만 허용.
        unpublished를 생략하면 쿼리 파라미터를 보내지 않는다(현재 기본값 확인용)."""
        info: dict = {"title": title}
        if document_title:
            info["documentTitle"] = document_title
        params = None if unpublished is None else {"unpublished": str(unpublished).lower()}
        return await self._request("POST", f"{BASE_URL}/forms", params=params, json={"info": info})

    async def get(self, form_id: str, fields: str | None = None) -> dict:
        """forms.get (읽기 쿼터). 구조·설정·질문 ID·publishSettings·responderUri·linkedSheetId. 응답은 없다."""
        params = {"fields": fields} if fields else None
        return await self._request("GET", f"{BASE_URL}/forms/{form_id}", params=params)

    async def batch_update(
        self,
        form_id: str,
        requests: list[dict],
        include_form_in_response: bool = False,
        required_revision_id: str | None = None,
    ) -> dict:
        """forms.batchUpdate (쓰기 쿼터 1회, 안의 요청 수 무관). 원자적. 요청은 배열 순서대로 검증된다.
        replies[]는 requests와 1:1이고 createItem이면 {itemId, questionId[]}가 온다."""
        body: dict = {"requests": requests, "includeFormInResponse": include_form_in_response}
        if required_revision_id:
            body["writeControl"] = {"requiredRevisionId": required_revision_id}
        return await self._request("POST", f"{BASE_URL}/forms/{form_id}:batchUpdate", json=body)

    async def set_publish_settings(self, form_id: str, is_published: bool, is_accepting_responses: bool) -> dict:
        """forms.setPublishSettings (쓰기 쿼터). 게시·게시 취소·응답 받기 중단/재개.
        is_published=False면 is_accepting_responses는 강제로 False. 레거시 폼(publishSettings 없음)은 에러."""
        body = {
            "publishSettings": {
                "publishState": {"isPublished": is_published, "isAcceptingResponses": is_accepting_responses}
            },
            "updateMask": "publishState",
        }
        return await self._request("POST", f"{BASE_URL}/forms/{form_id}:setPublishSettings", json=body)

    # --- responses (읽기 전용) ---

    async def list_responses(
        self,
        form_id: str,
        filter: str | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
        fields: str | None = None,
    ) -> dict:
        """forms.responses.list (expensive read 쿼터). filter는 `timestamp > RFC3339` / `timestamp >= RFC3339`만.
        pageSize 기본·최대 5000. 응답 항목에는 formId가 빠진다."""
        params: dict = {}
        if filter:
            params["filter"] = filter
        if page_size:
            params["pageSize"] = page_size
        if page_token:
            params["pageToken"] = page_token
        if fields:
            params["fields"] = fields
        return await self._request("GET", f"{BASE_URL}/forms/{form_id}/responses", params=params or None)

    async def get_response(self, form_id: str, response_id: str) -> dict:
        """forms.responses.get (읽기 쿼터)."""
        return await self._request("GET", f"{BASE_URL}/forms/{form_id}/responses/{response_id}")
