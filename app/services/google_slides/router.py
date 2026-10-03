"""/google/slides/... 시나리오 엔드포인트. 얇은 층, 옮기지 않는다."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.oauth import access_token_dependency
from app.services.google_drive.client import DriveApiError, DriveClient
from app.services.google_slides import usecases
from app.services.google_slides.client import SlidesApiError, SlidesClient

router = APIRouter(prefix="/google/slides", tags=["google_slides"])

google_token = access_token_dependency("google")


def _slides(token: str = Depends(google_token)) -> SlidesClient:
    return SlidesClient(token)


def _drive(token: str = Depends(google_token)) -> DriveClient:
    return DriveClient(token)


def _to_http(e: SlidesApiError | DriveApiError) -> HTTPException:
    return HTTPException(e.status, {"api": type(e).__name__, "message": e.message, "rate_limit": e.is_rate_limit, "body": e.body})


# ---------- 배관 ----------


class CreateEmptyRequest(BaseModel):
    title: str
    folder_id: str | None = None


@router.post("/create-empty")
async def create_empty(req: CreateEmptyRequest, slides: SlidesClient = Depends(_slides), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.create_empty_presentation(slides, drive, req.title, req.folder_id)
    except (SlidesApiError, DriveApiError) as e:
        raise _to_http(e)


@router.get("/read/{presentation_id}")
async def read(presentation_id: str, slides: SlidesClient = Depends(_slides), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.read_presentation(slides, drive, presentation_id)
    except (SlidesApiError, DriveApiError) as e:
        raise _to_http(e)


# ---------- 유즈케이스 2 ----------


@router.post("/upload-template")
async def upload_template(
    pptx: UploadFile = File(..., description="태그({{team_name}} 등)가 들어간 pptx 템플릿"),
    name: str = Form(...),
    folder_id: str | None = Form(default=None),
    drive: DriveClient = Depends(_drive),
):
    try:
        return await usecases.upload_template(drive, name, await pptx.read(), folder_id)
    except DriveApiError as e:
        raise _to_http(e)


class GroupIn(BaseModel):
    team_name: str
    member_emails: list[str] = []


class CreateGroupPresentationsRequest(BaseModel):
    folder_id: str
    activity_name: str
    title_template: str = "{{activity_name}} - {{team_name}}"
    template_presentation_id: str  # /upload-template 결과의 id
    groups: list[GroupIn]
    due: str | None = None
    notify: bool = False
    share_message: str | None = None


@router.post("/create-group-presentations")
async def create_group_presentations(
    req: CreateGroupPresentationsRequest, slides: SlidesClient = Depends(_slides), drive: DriveClient = Depends(_drive)
):
    groups = [usecases.GroupSpec(g.team_name, g.member_emails) for g in req.groups]
    return await usecases.create_group_presentations(
        slides, drive, req.folder_id, req.activity_name, req.title_template, req.template_presentation_id, groups,
        due=req.due, notify=req.notify, share_message=req.share_message,
    )


# ---------- 유즈케이스 3 ----------


class CloseSubmissionRequest(BaseModel):
    presentation_ids: list[str]
    to_role: str = "commenter"  # commenter | reader
    keep_emails: list[str] = []


@router.post("/close-submission")
async def close_submission(req: CloseSubmissionRequest, drive: DriveClient = Depends(_drive)):
    """마감 처리. Docs와 같은 함수. 이어서 /export/{id}."""
    return await usecases.close_submissions(drive, req.presentation_ids, req.to_role, req.keep_emails)


class RestoreRequest(BaseModel):
    presentation_id: str
    emails: list[str]


@router.post("/restore-edit-access")
async def restore_edit_access(req: RestoreRequest, drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.restore_editors(drive, req.presentation_id, req.emails)
    except DriveApiError as e:
        raise _to_http(e)


@router.get("/permissions/{presentation_id}")
async def permissions(presentation_id: str, drive: DriveClient = Depends(_drive)):
    try:
        return await drive.list_permissions(presentation_id)
    except DriveApiError as e:
        raise _to_http(e)


# ---------- 유즈케이스 4 ----------


@router.get("/export/{presentation_id}")
async def export(presentation_id: str, fmt: str = Query(default="pptx"), drive: DriveClient = Depends(_drive)):
    try:
        exported = await usecases.export_presentation(drive, presentation_id, fmt)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except DriveApiError as e:
        raise _to_http(e)
    return Response(
        content=exported.content,
        media_type=exported.mime_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(exported.filename)}"},
    )
