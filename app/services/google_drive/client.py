"""Google Drive REST 호출만. 다른 서비스의 client를 import하지 않는다.

Docs·Sheets·Slides·Forms 폴더 안에 Drive 호출을 두지 않고 전부 여기에 모은다
(files.get, 폴더 지정, 목록·검색·삭제·공유, files.export, changes.watch).
엔드포인트·쿼터 단위는 docs/google_drive.md 4절·8절.
"""

import json

import httpx

BASE_URL = "https://www.googleapis.com/drive/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3"

# Document 공통 모델 채우는 데 필요한 최소 필드. 쿼터는 fields 수와 무관하지만 응답 크기를 줄인다.
DOCUMENT_META_FIELDS = "id,name,mimeType,webViewLink,createdTime,modifiedTime,owners(displayName),parents,trashed,contentRestrictions(readOnly,reason,restrictionTime)"

MIME_FOLDER = "application/vnd.google-apps.folder"
MIME_DOC = "application/vnd.google-apps.document"
MIME_SHEET = "application/vnd.google-apps.spreadsheet"
MIME_SLIDES = "application/vnd.google-apps.presentation"
MIME_FORM = "application/vnd.google-apps.form"

# files.export 대상 형식 (Docs 기준). 10MB 상한.
EXPORT_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "txt": "text/plain",
    "md": "text/markdown",
    "html": "text/html",
}
# files.export 대상 형식 (Slides 기준). Drive에 Slides용 이미지 형식(png/jpeg/svg)은 없다 → 슬라이드 이미지는 Slides getThumbnail.
SLIDES_EXPORT_MIME = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
    "txt": "text/plain",
    "odp": "application/vnd.oasis.opendocument.presentation",
}
MIME_PPTX = SLIDES_EXPORT_MIME["pptx"]

PERMISSION_FIELDS = "id,type,role,emailAddress,displayName,expirationTime,pendingOwner"


class DriveApiError(Exception):
    """Drive 에러 응답. 403은 권한 부족일 수도, rate limit일 수도 있어 `reason`으로 분기한다."""

    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body
        err = body.get("error", {}) if isinstance(body, dict) else {}
        details = err.get("errors") or [{}]
        self.reason: str | None = details[0].get("reason") if details else None
        self.message: str = err.get("message", str(body))
        super().__init__(f"Drive {status} {self.reason}: {self.message}")

    @property
    def is_rate_limit(self) -> bool:
        return self.status == 429 or self.reason in {"rateLimitExceeded", "userRateLimitExceeded"}


class DriveClient:
    def __init__(self, access_token: str, http: httpx.AsyncClient | None = None):
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._http = http or httpx.AsyncClient(timeout=30)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        resp = await self._http.request(method, url, headers={**self._headers, **kwargs.pop("headers", {})}, **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = {"error": {"message": resp.text}}
            raise DriveApiError(resp.status_code, body)
        return resp

    # --- files ---

    async def get_file(self, file_id: str, fields: str = DOCUMENT_META_FIELDS) -> dict:
        """files.get (쿼터 5)."""
        resp = await self._request("GET", f"{BASE_URL}/files/{file_id}", params={"fields": fields})
        return resp.json()

    async def move_file(self, file_id: str, to_folder_id: str, from_folder_id: str | None = None) -> dict:
        """files.update로 폴더 이동 (쿼터 50). Docs `documents.create`는 폴더를 못 정하므로 생성 후 여기로 옮긴다."""
        params: dict[str, str] = {"addParents": to_folder_id, "fields": DOCUMENT_META_FIELDS}
        if from_folder_id:
            params["removeParents"] = from_folder_id
        resp = await self._request("PATCH", f"{BASE_URL}/files/{file_id}", params=params, json={})
        return resp.json()

    async def copy_file(self, file_id: str, name: str, parent_folder_id: str | None = None) -> dict:
        """files.copy. 템플릿(Slides 등)을 통째로 복사한다. drive.file에서는 앱이 접근 가능한 원본만 복사할 수 있고,
        사본은 앱이 만든 파일이 된다. parent_folder_id가 없으면 원본의 (앱이 볼 수 있는) 부모 폴더를 물려받는다(공식 문서)."""
        metadata: dict = {"name": name}
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]
        resp = await self._request(
            "POST", f"{BASE_URL}/files/{file_id}/copy", params={"fields": DOCUMENT_META_FIELDS}, json=metadata
        )
        return resp.json()

    async def create_folder(self, name: str, parent_folder_id: str | None = None) -> dict:
        """files.create로 폴더 생성 (쿼터 50). drive.file scope에서는 앱이 만든 폴더만 보이므로,
        문서를 폴더에 넣는 시나리오는 이 폴더 안에서만 동작한다. 사용자가 웹에서 만든 폴더는 404가 난다."""
        metadata: dict = {"name": name, "mimeType": MIME_FOLDER}
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]
        resp = await self._request(
            "POST", f"{BASE_URL}/files", params={"fields": DOCUMENT_META_FIELDS}, json=metadata
        )
        return resp.json()

    async def rename_file(self, file_id: str, name: str) -> dict:
        resp = await self._request(
            "PATCH", f"{BASE_URL}/files/{file_id}", params={"fields": DOCUMENT_META_FIELDS}, json={"name": name}
        )
        return resp.json()

    async def create_from_content(
        self,
        name: str,
        content: bytes | str,
        source_mime_type: str,
        target_mime_type: str = MIME_DOC,
        parent_folder_id: str | None = None,
    ) -> dict:
        """files.create multipart 업로드 + 변환 (5MB 이하). Markdown/HTML → Docs 변환이 대표 용도.

        5MB 초과는 resumable 업로드가 필요하며 아직 구현하지 않았다 (필요해지면 추가).
        """
        metadata: dict = {"name": name, "mimeType": target_mime_type}
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]
        if isinstance(content, str):
            content = content.encode("utf-8")
        files = {
            "metadata": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
            "file": ("file", content, source_mime_type),
        }
        resp = await self._request(
            "POST",
            f"{UPLOAD_URL}/files",
            params={"uploadType": "multipart", "fields": DOCUMENT_META_FIELDS},
            files=files,
        )
        return resp.json()

    async def export_file(self, file_id: str, mime_type: str) -> bytes:
        """files.export (쿼터 200). 결과는 10MB까지. Docs → pdf/docx/text/markdown 등."""
        resp = await self._request("GET", f"{BASE_URL}/files/{file_id}/export", params={"mimeType": mime_type})
        return resp.content

    async def list_files(self, q: str | None = None, page_size: int = 20, page_token: str | None = None) -> dict:
        """files.list (쿼터 100, 비싸다). drive.file이면 앱이 접근 가능한 파일만 나온다."""
        params: dict = {"pageSize": page_size, "fields": f"nextPageToken,files({DOCUMENT_META_FIELDS})"}
        if q:
            params["q"] = q
        if page_token:
            params["pageToken"] = page_token
        resp = await self._request("GET", f"{BASE_URL}/files", params=params)
        return resp.json()

    async def trash_file(self, file_id: str) -> dict:
        """휴지통으로 이동 (files.update trashed=true). 영구 삭제는 delete_file."""
        resp = await self._request(
            "PATCH", f"{BASE_URL}/files/{file_id}", params={"fields": "id,trashed"}, json={"trashed": True}
        )
        return resp.json()

    async def delete_file(self, file_id: str) -> None:
        """files.delete 영구 삭제. 휴지통을 거치지 않는다."""
        await self._request("DELETE", f"{BASE_URL}/files/{file_id}")

    # --- 편집 잠금 (contentRestrictions) ---

    async def set_read_only(self, file_id: str, read_only: bool, reason: str | None = None) -> dict:
        """files.update contentRestrictions. readOnly=true면 편집자 포함 모두 편집 불가, 보기는 가능.
        **현재 유즈케이스에서는 쓰지 않는다** (잠기면 소유자도 API 편집이 403이라 마감 처리는 permissions로 한다, 2026-10-03 결정).
        동작 실측 기록은 docs/google_drive.md 10절, samples/google_docs/uc3-lock-for-submission.json."""
        restriction: dict = {"readOnly": read_only}
        if read_only and reason:
            restriction["reason"] = reason
        resp = await self._request(
            "PATCH",
            f"{BASE_URL}/files/{file_id}",
            params={"fields": DOCUMENT_META_FIELDS},
            json={"contentRestrictions": [restriction]},
        )
        return resp.json()

    # --- permissions ---

    async def share_with_user(
        self,
        file_id: str,
        email: str,
        role: str = "reader",
        notify: bool = False,
        message: str | None = None,
        expiration_time: str | None = None,
    ) -> dict:
        """permissions.create. role: reader | commenter | writer. expiration_time은 RFC3339 (user/group만, 1년 이내)."""
        body: dict = {"type": "user", "role": role, "emailAddress": email}
        if expiration_time:
            body["expirationTime"] = expiration_time
        params: dict = {"sendNotificationEmail": str(notify).lower(), "fields": PERMISSION_FIELDS}
        if notify and message:
            params["emailMessage"] = message
        resp = await self._request("POST", f"{BASE_URL}/files/{file_id}/permissions", params=params, json=body)
        return resp.json()

    async def list_permissions(self, file_id: str) -> list[dict]:
        resp = await self._request(
            "GET", f"{BASE_URL}/files/{file_id}/permissions", params={"fields": f"permissions({PERMISSION_FIELDS})"}
        )
        return resp.json().get("permissions", [])

    async def update_permission_role(self, file_id: str, permission_id: str, role: str) -> dict:
        """permissions.update. 편집자(writer) → commenter/reader로 낮추는 데 쓴다."""
        resp = await self._request(
            "PATCH",
            f"{BASE_URL}/files/{file_id}/permissions/{permission_id}",
            params={"fields": PERMISSION_FIELDS},
            json={"role": role},
        )
        return resp.json()

    async def delete_permission(self, file_id: str, permission_id: str) -> None:
        await self._request("DELETE", f"{BASE_URL}/files/{file_id}/permissions/{permission_id}")

    # --- changes (변경 감지: 폴링 우선, push는 9절) ---

    async def get_start_page_token(self) -> str:
        resp = await self._request("GET", f"{BASE_URL}/changes/startPageToken")
        return resp.json()["startPageToken"]

    async def list_changes(self, page_token: str) -> dict:
        resp = await self._request(
            "GET",
            f"{BASE_URL}/changes",
            params={"pageToken": page_token, "fields": f"nextPageToken,newStartPageToken,changes(fileId,removed,file({DOCUMENT_META_FIELDS}))"},
        )
        return resp.json()
