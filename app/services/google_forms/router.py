"""/google/forms/... 시나리오 엔드포인트. 얇은 층, 옮기지 않는다."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.oauth import access_token_dependency
from app.services.google_drive.client import DriveApiError, DriveClient
from app.services.google_forms import usecases
from app.services.google_forms.client import FormsApiError, FormsClient
from app.services.google_sheets.client import SheetsApiError, SheetsClient

router = APIRouter(prefix="/google/forms", tags=["google_forms"])

google_token = access_token_dependency("google")


def _forms(token: str = Depends(google_token)) -> FormsClient:
    return FormsClient(token)


def _drive(token: str = Depends(google_token)) -> DriveClient:
    return DriveClient(token)


def _sheets(token: str = Depends(google_token)) -> SheetsClient:
    return SheetsClient(token)


def _to_http(e: FormsApiError | DriveApiError | SheetsApiError) -> HTTPException:
    return HTTPException(e.status, {"api": type(e).__name__, "message": e.message, "rate_limit": e.is_rate_limit, "body": e.body})


ERRORS = (FormsApiError, DriveApiError, SheetsApiError)


class CreateFormRequest(BaseModel):
    title: str
    folder_id: str | None = None
    description: str | None = None
    items: list[dict] = []  # Forms Item 객체 배열(템플릿). createItem으로 순서대로 들어간다
    email_collection: str | None = None  # DO_NOT_COLLECT | VERIFIED | RESPONDER_INPUT
    quiz: bool = False
    publish: bool = True


@router.post("/create-form")
async def create_form(req: CreateFormRequest, forms: FormsClient = Depends(_forms), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.create_form(
            forms, drive, req.title, req.folder_id, req.description, req.items, req.email_collection, req.quiz, req.publish
        )
    except ERRORS as e:
        raise _to_http(e)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/read/{form_id}")
async def read(form_id: str, forms: FormsClient = Depends(_forms), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.read_form(forms, drive, form_id)
    except ERRORS as e:
        raise _to_http(e)


class PublishStateRequest(BaseModel):
    published: bool = True
    accepting_responses: bool


@router.post("/set-publish-state/{form_id}")
async def set_publish_state(
    form_id: str, req: PublishStateRequest, forms: FormsClient = Depends(_forms), drive: DriveClient = Depends(_drive)
):
    try:
        return await usecases.set_publish_state(forms, drive, form_id, req.published, req.accepting_responses)
    except ERRORS as e:
        raise _to_http(e)


class RespondersRequest(BaseModel):
    emails: list[str]


@router.post("/restrict-responders/{form_id}")
async def restrict_responders(form_id: str, req: RespondersRequest, drive: DriveClient = Depends(_drive)):
    return await usecases.restrict_responders(drive, form_id, req.emails)


@router.post("/allow-anyone/{form_id}")
async def allow_anyone(form_id: str, drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.allow_anyone_with_link(drive, form_id)
    except DriveApiError as e:
        raise _to_http(e)


@router.post("/remove-anyone/{form_id}")
async def remove_anyone(form_id: str, drive: DriveClient = Depends(_drive)):
    try:
        await usecases.remove_anyone_with_link(drive, form_id)
        return await usecases.list_permissions(drive, form_id)
    except DriveApiError as e:
        raise _to_http(e)


class SettingsRequest(BaseModel):
    email_collection: str | None = None
    quiz: bool | None = None


@router.post("/update-settings/{form_id}")
async def update_settings(form_id: str, req: SettingsRequest, forms: FormsClient = Depends(_forms), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.update_settings(forms, drive, form_id, req.email_collection, req.quiz)
    except ERRORS as e:
        raise _to_http(e)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/permissions/{form_id}")
async def permissions(form_id: str, drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.list_permissions(drive, form_id)
    except DriveApiError as e:
        raise _to_http(e)


class CopyFormRequest(BaseModel):
    name: str
    folder_id: str | None = None


@router.post("/copy-form/{form_id}")
async def copy_form(form_id: str, req: CopyFormRequest, forms: FormsClient = Depends(_forms), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.copy_form(forms, drive, form_id, req.name, req.folder_id)
    except ERRORS as e:
        raise _to_http(e)


# ---------- 7·8 열기·마감·재개 ----------


@router.post("/open/{form_id}")
async def open_form(form_id: str, forms: FormsClient = Depends(_forms), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.open_form(forms, drive, form_id)
    except ERRORS as e:
        raise _to_http(e)


@router.post("/close/{form_id}")
async def close_form(form_id: str, forms: FormsClient = Depends(_forms), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.close_form(forms, drive, form_id)
    except ERRORS as e:
        raise _to_http(e)


@router.post("/reopen/{form_id}")
async def reopen_form(form_id: str, forms: FormsClient = Depends(_forms), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.reopen_form(forms, drive, form_id)
    except ERRORS as e:
        raise _to_http(e)


# ---------- 3 조별 동료평가 폼 ----------


class MemberIn(BaseModel):
    name: str
    email: str


class PeerGroupIn(BaseModel):
    team_name: str
    members: list[MemberIn]


class CreateGroupFormsRequest(BaseModel):
    folder_id: str
    activity_name: str
    groups: list[PeerGroupIn]
    criteria: list[str]
    scale: list[str] | None = None
    title_template: str = "{{activity_name}} 동료평가 - {{team_name}}"
    description: str | None = None
    extra_items: list[dict] = []


@router.post("/create-group-forms")
async def create_group_forms(req: CreateGroupFormsRequest, forms: FormsClient = Depends(_forms), drive: DriveClient = Depends(_drive)):
    groups = [usecases.PeerGroup(g.team_name, [usecases.Member(m.name, m.email) for m in g.members]) for g in req.groups]
    return await usecases.create_group_forms(
        forms, drive, req.folder_id, req.activity_name, groups, req.criteria, req.scale, req.title_template, req.description, req.extra_items
    )


# ---------- 6 제출 현황 · 9 수집·집계 · 10 점수 · 11 동료평가 ----------


class RosterRequest(BaseModel):
    roster_emails: list[str]


@router.post("/submission-status/{form_id}")
async def submission_status(form_id: str, req: RosterRequest, forms: FormsClient = Depends(_forms)):
    try:
        return await usecases.get_submission_status(forms, form_id, req.roster_emails)
    except FormsApiError as e:
        raise _to_http(e)


@router.get("/responses/{form_id}")
async def responses(form_id: str, since: str | None = None, forms: FormsClient = Depends(_forms)):
    try:
        return await usecases.collect_responses(forms, form_id, since)
    except FormsApiError as e:
        raise _to_http(e)


@router.get("/summary/{form_id}")
async def summary(form_id: str, forms: FormsClient = Depends(_forms)):
    try:
        return await usecases.summarize_responses(forms, form_id)
    except FormsApiError as e:
        raise _to_http(e)


@router.get("/quiz-scores/{form_id}")
async def quiz_scores(form_id: str, forms: FormsClient = Depends(_forms)):
    try:
        return await usecases.collect_quiz_scores(forms, form_id)
    except FormsApiError as e:
        raise _to_http(e)


class PeerReviewsRequest(BaseModel):
    reviewees: dict[str, str] | None = None  # 격자 행 질문 ID → 피평가자 이메일 (create-group-forms 결과)
    exclude_self: bool = True


@router.post("/peer-reviews/{form_id}")
async def peer_reviews(form_id: str, req: PeerReviewsRequest, forms: FormsClient = Depends(_forms)):
    try:
        return await usecases.collect_peer_reviews(forms, form_id, req.reviewees, req.exclude_self)
    except FormsApiError as e:
        raise _to_http(e)


# ---------- 12 파일 · 13 시트 ----------


@router.get("/export/{form_id}")
async def export(form_id: str, fmt: str = "csv", forms: FormsClient = Depends(_forms)):
    try:
        exported = await usecases.export_responses(forms, form_id, fmt)
    except FormsApiError as e:
        raise _to_http(e)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(
        exported.content,
        media_type=exported.mime_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(exported.filename)}"},
    )


class ExportToSheetRequest(BaseModel):
    spreadsheet_id: str | None = None  # 없으면 새로 만든다
    folder_id: str | None = None
    title: str | None = None
    previous_columns: int | None = None  # 다시 내보낼 때 지난번 결과의 columns


@router.post("/export-to-sheet/{form_id}")
async def export_to_sheet(
    form_id: str,
    req: ExportToSheetRequest,
    forms: FormsClient = Depends(_forms),
    drive: DriveClient = Depends(_drive),
    sheets: SheetsClient = Depends(_sheets),
):
    try:
        return await usecases.export_responses_to_sheet(
            forms, drive, sheets, form_id, req.spreadsheet_id, req.folder_id, req.title, req.previous_columns
        )
    except ERRORS as e:
        raise _to_http(e)


class FromTemplateRequest(BaseModel):
    template_form_id: str  # 앱이 만든 폼 또는 Picker로 고른 폼
    name: str
    folder_id: str | None = None
    title: str | None = None
    responder_emails: list[str] = []
    publish: bool = True


@router.post("/create-from-template")
async def create_from_template(req: FromTemplateRequest, forms: FormsClient = Depends(_forms), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.create_form_from_template(
            forms, drive, req.template_form_id, req.name, req.folder_id, req.title, req.responder_emails or None, req.publish
        )
    except ERRORS as e:
        raise _to_http(e)


# ---------- 12절 실측용 ----------


class RawCreateRequest(BaseModel):
    title: str
    unpublished: bool | None = None


@router.post("/experiments/create-raw")
async def create_raw(req: RawCreateRequest, forms: FormsClient = Depends(_forms)):
    try:
        return await usecases.create_raw(forms, req.title, req.unpublished)
    except FormsApiError as e:
        raise _to_http(e)


class ViaDriveRequest(BaseModel):
    title: str
    folder_id: str | None = None


@router.post("/experiments/create-via-drive")
async def create_via_drive(req: ViaDriveRequest, forms: FormsClient = Depends(_forms), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.create_via_drive(forms, drive, req.title, req.folder_id)
    except ERRORS as e:
        raise _to_http(e)
