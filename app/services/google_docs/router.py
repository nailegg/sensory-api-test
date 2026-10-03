"""/google/docs/... 시나리오 엔드포인트. 얇은 층, 옮기지 않는다."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.oauth import access_token_dependency
from app.services.google_docs import usecases
from app.services.google_docs.client import DocsApiError, DocsClient
from app.services.google_drive.client import DriveApiError, DriveClient

router = APIRouter(prefix="/google/docs", tags=["google_docs"])

google_token = access_token_dependency("google")


def _docs(token: str = Depends(google_token)) -> DocsClient:
    return DocsClient(token)


def _drive(token: str = Depends(google_token)) -> DriveClient:
    return DriveClient(token)


def _to_http(e: DocsApiError | DriveApiError) -> HTTPException:
    return HTTPException(e.status, {"api": type(e).__name__, "message": e.message, "rate_limit": e.is_rate_limit, "body": e.body})


# ---------- 배관 ----------


class CreateEmptyRequest(BaseModel):
    title: str
    folder_id: str | None = None


@router.post("/create-empty")
async def create_empty(req: CreateEmptyRequest, docs: DocsClient = Depends(_docs), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.create_empty_document(docs, drive, req.title, req.folder_id)
    except (DocsApiError, DriveApiError) as e:
        raise _to_http(e)


@router.get("/read/{document_id}")
async def read(document_id: str, docs: DocsClient = Depends(_docs), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.read_document(docs, drive, document_id)
    except (DocsApiError, DriveApiError) as e:
        raise _to_http(e)


# ---------- 유즈케이스 2 ----------


class GroupIn(BaseModel):
    team_name: str
    member_emails: list[str] = []


class CreateGroupDocumentsRequest(BaseModel):
    folder_id: str
    activity_name: str
    title_template: str = "{{activity_name}} - {{team_name}}"
    body_template: str | None = None  # Markdown 템플릿 (method=markdown | docs_api)
    template_document_id: str | None = None  # Google Doc 템플릿 ID (Picker로 고른 문서 또는 앱이 만든 문서). body_template과 둘 중 하나
    groups: list[GroupIn]
    due: str | None = None
    method: str = "markdown"  # markdown | docs_api
    notify: bool = False
    share_message: str | None = None


@router.post("/create-group-documents")
async def create_group_documents(
    req: CreateGroupDocumentsRequest, docs: DocsClient = Depends(_docs), drive: DriveClient = Depends(_drive)
):
    groups = [usecases.GroupSpec(g.team_name, g.member_emails) for g in req.groups]
    try:
        return await usecases.create_group_documents(
            docs, drive, req.folder_id, req.activity_name, req.title_template, req.body_template, groups,
            due=req.due, method=req.method, notify=req.notify, share_message=req.share_message,
            template_document_id=req.template_document_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------- 유즈케이스 3 ----------


class DowngradeRequest(BaseModel):
    document_id: str
    to_role: str = "commenter"
    keep_emails: list[str] = []  # 조교·공동 교수자 등 writer 유지


@router.post("/revoke-edit-access")
async def revoke_edit_access(req: DowngradeRequest, drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.downgrade_editors(drive, req.document_id, req.to_role, req.keep_emails)
    except DriveApiError as e:
        raise _to_http(e)


class CloseSubmissionRequest(BaseModel):
    document_ids: list[str]
    to_role: str = "commenter"  # commenter | reader
    keep_emails: list[str] = []


@router.post("/close-submission")
async def close_submission(req: CloseSubmissionRequest, drive: DriveClient = Depends(_drive)):
    """마감 처리. 서비스 스케줄러가 due 시각에 호출하는 것을 가정한 엔드포인트. 이어서 /export/{id}."""
    return await usecases.close_submissions(drive, req.document_ids, req.to_role, req.keep_emails)


class RestoreRequest(BaseModel):
    document_id: str
    emails: list[str]


@router.post("/restore-edit-access")
async def restore_edit_access(req: RestoreRequest, drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.restore_editors(drive, req.document_id, req.emails)
    except DriveApiError as e:
        raise _to_http(e)


class ShareRequest(BaseModel):
    document_id: str
    emails: list[str]
    role: str = "writer"
    notify: bool = False
    message: str | None = None
    expiration_time: str | None = None  # RFC3339. 3안 검증용


@router.post("/share")
async def share(req: ShareRequest, drive: DriveClient = Depends(_drive)):
    results = []
    for email in req.emails:
        try:
            perm = await drive.share_with_user(req.document_id, email, req.role, req.notify, req.message, req.expiration_time)
            results.append({"email": email, "ok": True, "permission": perm})
        except DriveApiError as e:
            results.append({"email": email, "ok": False, "status": e.status, "reason": e.reason, "message": e.message})
    return results


@router.get("/permissions/{document_id}")
async def permissions(document_id: str, drive: DriveClient = Depends(_drive)):
    try:
        return await drive.list_permissions(document_id)
    except DriveApiError as e:
        raise _to_http(e)


# ---------- 유즈케이스 4 ----------


@router.get("/export/{document_id}")
async def export(document_id: str, fmt: str = Query(default="docx"), drive: DriveClient = Depends(_drive)):
    try:
        exported = await usecases.export_document(drive, document_id, fmt)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except DriveApiError as e:
        raise _to_http(e)
    return Response(
        content=exported.content,
        media_type=exported.mime_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(exported.filename)}"},
    )
