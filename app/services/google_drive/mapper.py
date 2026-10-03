"""Drive 응답 dict → core/models 순수 변환. 네트워크 호출도 client import도 없다."""

from app.core.models import Document, DocumentKind

_MIME_TO_KIND = {
    "application/vnd.google-apps.document": DocumentKind.DOC,
    "application/vnd.google-apps.spreadsheet": DocumentKind.SHEET,
    "application/vnd.google-apps.presentation": DocumentKind.SLIDES,
    "application/vnd.google-apps.form": DocumentKind.FORM,
    "application/vnd.google-apps.folder": DocumentKind.FOLDER,
}


def kind_from_mime(mime_type: str | None) -> DocumentKind:
    return _MIME_TO_KIND.get(mime_type or "", DocumentKind.FILE)


def document_from_drive_file(file: dict, text: str | None = None) -> Document:
    """`files.get` 응답(DOCUMENT_META_FIELDS 기준) → Document.

    Docs/Sheets/Slides/Forms mapper는 자기 API 응답으로 title·text를 보강한 뒤 이 함수를 쓴다.
    """
    owners = file.get("owners") or []
    parents = file.get("parents") or []
    return Document(
        id=file["id"],
        kind=kind_from_mime(file.get("mimeType")),
        title=file.get("name", ""),
        url=file.get("webViewLink"),
        mime_type=file.get("mimeType"),
        owner=owners[0].get("displayName") if owners else None,
        created_at=file.get("createdTime"),
        modified_at=file.get("modifiedTime"),
        parent_folder_id=parents[0] if parents else None,
        trashed=bool(file.get("trashed", False)),
        locked=any(r.get("readOnly") for r in file.get("contentRestrictions") or []),
        text=text,
    )
