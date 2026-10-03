"""Docs 시나리오 흐름. 여러 client와 mapper를 엮는다. FastAPI를 import하지 않는다.

유즈케이스(docs/google_docs.md 1절, 2026-10-03 확정):
1. 액티비티 폴더 생성 → google_drive.usecases.create_folder
2. 템플릿으로 그룹마다 문서 생성 + 그룹원 편집 권한 → create_group_documents
3. 마감 시 편집 비활성화 → close_submissions (문서마다 downgrade_editors). 문서 잠금(contentRestrictions) 방식은 교수자도 API 편집이 막혀 쓰지 않기로 함(2026-10-03)
4. 마감 시 파일로 내보내기 → export_document
"""

import re
from dataclasses import dataclass, field

from app.core.models import Document
from app.services.google_docs.client import DocsApiError, DocsClient
from app.services.google_docs.mapper import document_from_docs
from app.services.google_drive.client import EXPORT_MIME, MIME_DOC, DriveApiError, DriveClient
from app.services.google_drive.mapper import document_from_drive_file

# ---------- 템플릿 ----------

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_template(template: str, variables: dict[str, str]) -> str:
    """`{{team_name}}` 형태의 플레이스홀더를 치환한다. 없는 변수는 그대로 둔다 (Markdown의 다른 중괄호와 충돌 방지)."""

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        return str(variables[key]) if key in variables else m.group(0)

    return _PLACEHOLDER.sub(_sub, template)


@dataclass
class GroupSpec:
    team_name: str
    member_emails: list[str] = field(default_factory=list)


@dataclass
class ShareResult:
    email: str
    ok: bool
    permission_id: str | None = None
    error: str | None = None


@dataclass
class GroupDocumentResult:
    team_name: str
    document: Document | None
    shares: list[ShareResult] = field(default_factory=list)
    error: str | None = None


# ---------- 읽기·생성 배관 ----------


async def read_document(docs: DocsClient, drive: DriveClient, document_id: str) -> Document:
    """문서 본문(평문) + Drive 메타데이터 → Document."""
    doc = await docs.get(document_id, include_tabs_content=True)
    drive_file = await drive.get_file(document_id)
    return document_from_docs(doc, drive_file, include_text=True)


async def create_empty_document(docs: DocsClient, drive: DriveClient, title: str, folder_id: str | None = None) -> Document:
    """빈 문서 생성 → (선택) 폴더로 이동 → Drive 메타데이터 → Document.

    documents.create는 폴더를 못 정하므로 Drive files.update(addParents)로 옮긴다.
    """
    doc = await docs.create(title)
    document_id = doc["documentId"]
    if folder_id:
        drive_file = await drive.move_file(document_id, to_folder_id=folder_id)
    else:
        drive_file = await drive.get_file(document_id)
    return document_from_docs(doc, drive_file)


async def create_document_from_markdown(drive: DriveClient, title: str, markdown: str, folder_id: str | None) -> Document:
    """방식 A: Markdown을 Drive에 올리며 Docs로 변환. 호출 1회, 서식(제목·굵게·목록) 유지."""
    drive_file = await drive.create_from_content(title, markdown, "text/markdown", MIME_DOC, folder_id)
    return document_from_drive_file(drive_file)


async def create_document_with_docs_api(
    docs: DocsClient, drive: DriveClient, title: str, plain_text: str, folder_id: str | None
) -> Document:
    """방식 B: documents.create → batchUpdate insertText(index 1) → 폴더 이동. 호출 3회, 서식 없음(평문).
    서식을 넣으려면 updateParagraphStyle 등을 인덱스 계산과 함께 추가해야 한다. 비교용."""
    doc = await docs.create(title)
    document_id = doc["documentId"]
    if plain_text:
        await docs.batch_update(document_id, [{"insertText": {"location": {"index": 1}, "text": plain_text}}])
    drive_file = await drive.move_file(document_id, to_folder_id=folder_id) if folder_id else await drive.get_file(document_id)
    return document_from_docs(doc, drive_file)


# ---------- 유즈케이스 2 ----------


async def share_document(
    drive: DriveClient, document_id: str, emails: list[str], role: str = "writer", notify: bool = False, message: str | None = None
) -> list[ShareResult]:
    """그룹원마다 permissions.create. 한 명이 실패해도 나머지는 계속한다."""
    results: list[ShareResult] = []
    for email in emails:
        try:
            perm = await drive.share_with_user(document_id, email, role=role, notify=notify, message=message)
            results.append(ShareResult(email=email, ok=True, permission_id=perm.get("id")))
        except DriveApiError as e:
            results.append(ShareResult(email=email, ok=False, error=f"{e.status} {e.reason}: {e.message}"))
    return results


async def create_group_documents(
    docs: DocsClient,
    drive: DriveClient,
    folder_id: str,
    activity_name: str,
    title_template: str,
    body_template: str,
    groups: list[GroupSpec],
    due: str | None = None,
    method: str = "markdown",
    notify: bool = False,
    share_message: str | None = None,
) -> list[GroupDocumentResult]:
    """그룹마다 템플릿을 채워 폴더 안에 문서를 만들고 그룹원에게 편집 권한을 준다.

    한 그룹이 실패해도 다음 그룹을 계속 만들고, 결과에 error를 담아 돌려준다.
    """
    results: list[GroupDocumentResult] = []
    for group in groups:
        variables = {"team_name": group.team_name, "activity_name": activity_name, "due": due or ""}
        title = render_template(title_template, variables)
        body = render_template(body_template, variables)
        try:
            if method == "docs_api":
                document = await create_document_with_docs_api(docs, drive, title, body, folder_id)
            else:
                document = await create_document_from_markdown(drive, title, body, folder_id)
        except (DriveApiError, DocsApiError) as e:
            results.append(GroupDocumentResult(team_name=group.team_name, document=None, error=str(e)))
            continue
        shares = await share_document(drive, document.id, group.member_emails, notify=notify, message=share_message)
        results.append(GroupDocumentResult(team_name=group.team_name, document=document, shares=shares))
    return results


# ---------- 유즈케이스 3 ----------


async def downgrade_editors(
    drive: DriveClient, document_id: str, to_role: str = "commenter", keep_emails: list[str] | None = None
) -> list[dict]:
    """문서 하나의 writer 권한을 to_role로 낮춘다. 소유자(owner)는 조건에 안 걸려 그대로 남는다.
    조교·공동 교수자처럼 writer를 유지해야 하는 사람은 keep_emails로 제외한다. 그룹원 수만큼 호출."""
    keep = {e.lower() for e in keep_emails or []}
    changed: list[dict] = []
    for perm in await drive.list_permissions(document_id):
        if perm.get("role") != "writer" or perm.get("type") not in {"user", "group"}:
            continue
        if (perm.get("emailAddress") or "").lower() in keep:
            continue
        changed.append(await drive.update_permission_role(document_id, perm["id"], to_role))
    return changed


@dataclass
class CloseResult:
    document_id: str
    downgraded: list[dict] = field(default_factory=list)
    error: str | None = None


async def close_submissions(
    drive: DriveClient, document_ids: list[str], to_role: str = "commenter", keep_emails: list[str] | None = None
) -> list[CloseResult]:
    """마감 처리. Synsory 스케줄러가 due 시각에 부른다. 문서마다 downgrade_editors를 실행하고,
    한 문서가 실패해도 나머지를 계속한다. 재실행해도 안전하다(이미 낮춰진 권한은 건너뜀).
    이 다음에 export_document를 호출해 제출본을 확보한다."""
    results: list[CloseResult] = []
    for document_id in document_ids:
        try:
            changed = await downgrade_editors(drive, document_id, to_role, keep_emails)
            results.append(CloseResult(document_id=document_id, downgraded=changed))
        except DriveApiError as e:
            results.append(CloseResult(document_id=document_id, error=f"{e.status} {e.reason}: {e.message}"))
    return results


async def restore_editors(drive: DriveClient, document_id: str, emails: list[str]) -> list[dict]:
    """되돌리기: 지정한 이메일의 권한을 다시 writer로."""
    wanted = {e.lower() for e in emails}
    changed: list[dict] = []
    for perm in await drive.list_permissions(document_id):
        if (perm.get("emailAddress") or "").lower() in wanted and perm.get("role") != "writer":
            changed.append(await drive.update_permission_role(document_id, perm["id"], "writer"))
    return changed


# ---------- 유즈케이스 4 ----------


@dataclass
class ExportedFile:
    document_id: str
    filename: str
    mime_type: str
    content: bytes


async def export_document(drive: DriveClient, document_id: str, fmt: str = "docx") -> ExportedFile:
    """files.export. Turnitin 등으로의 전송은 호출자(서비스 레포) 책임. 결과는 10MB까지."""
    if fmt not in EXPORT_MIME:
        raise ValueError(f"지원하지 않는 형식: {fmt}. 가능: {sorted(EXPORT_MIME)}")
    meta = await drive.get_file(document_id, fields="id,name")
    content = await drive.export_file(document_id, EXPORT_MIME[fmt])
    return ExportedFile(document_id=document_id, filename=f"{meta['name']}.{fmt}", mime_type=EXPORT_MIME[fmt], content=content)
