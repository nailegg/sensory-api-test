"""/google/sheets/... 시나리오 엔드포인트. 얇은 층, 옮기지 않는다."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.oauth import access_token_dependency
from app.services.google_drive.client import DriveApiError, DriveClient
from app.services.google_sheets import usecases
from app.services.google_sheets.client import SheetsApiError, SheetsClient

router = APIRouter(prefix="/google/sheets", tags=["google_sheets"])

google_token = access_token_dependency("google")


def _sheets(token: str = Depends(google_token)) -> SheetsClient:
    return SheetsClient(token)


def _drive(token: str = Depends(google_token)) -> DriveClient:
    return DriveClient(token)


def _to_http(e: SheetsApiError | DriveApiError) -> HTTPException:
    return HTTPException(e.status, {"api": type(e).__name__, "message": e.message, "rate_limit": e.is_rate_limit, "body": e.body})


# ---------- 배관 ----------


class CreateEmptyRequest(BaseModel):
    title: str
    folder_id: str | None = None
    sheet_names: list[str] | None = None


@router.post("/create-empty")
async def create_empty(req: CreateEmptyRequest, sheets: SheetsClient = Depends(_sheets), drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.create_empty_spreadsheet(sheets, drive, req.title, req.folder_id, req.sheet_names)
    except (SheetsApiError, DriveApiError) as e:
        raise _to_http(e)


@router.get("/read/{spreadsheet_id}")
async def read(
    spreadsheet_id: str,
    include_values: bool = Query(default=False),
    sheets: SheetsClient = Depends(_sheets),
    drive: DriveClient = Depends(_drive),
):
    try:
        return await usecases.read_spreadsheet(sheets, drive, spreadsheet_id, include_values)
    except (SheetsApiError, DriveApiError) as e:
        raise _to_http(e)


@router.get("/sheets/{spreadsheet_id}")
async def list_sheets(spreadsheet_id: str, sheets: SheetsClient = Depends(_sheets)):
    """시트 목록(sheetId·이름·보호 범위). lock-ranges·values?sheet_id= 에 넣을 sheetId를 여기서 얻는다."""
    try:
        return await usecases.list_sheets(sheets, spreadsheet_id)
    except SheetsApiError as e:
        raise _to_http(e)


class WriteValuesRequest(BaseModel):
    spreadsheet_id: str
    sheet_title: str
    cell_range: str  # 예: "B6:B9"
    values: list[list]
    value_input_option: str = "RAW"  # RAW | USER_ENTERED


@router.post("/write-values")
async def write_values(req: WriteValuesRequest, sheets: SheetsClient = Depends(_sheets)):
    """배관·실험용(보호 범위가 API 쓰기를 막는지, RAW vs USER_ENTERED 등)."""
    try:
        return await usecases.write_values(sheets, req.spreadsheet_id, req.sheet_title, req.cell_range, req.values, req.value_input_option)
    except SheetsApiError as e:
        raise _to_http(e)


# ---------- 유즈케이스 2 ----------


@router.post("/upload-template")
async def upload_template(
    xlsx: UploadFile = File(..., description="태그({{team_name}} 등)가 들어간 xlsx 템플릿"),
    name: str = Form(...),
    folder_id: str | None = Form(default=None),
    drive: DriveClient = Depends(_drive),
):
    try:
        return await usecases.upload_template(drive, name, await xlsx.read(), folder_id)
    except DriveApiError as e:
        raise _to_http(e)


class GroupIn(BaseModel):
    team_name: str
    member_emails: list[str] = []


class CreateGroupSheetsRequest(BaseModel):
    folder_id: str
    activity_name: str
    title_template: str = "{{activity_name}} - {{team_name}}"
    template_spreadsheet_id: str | None = None  # copy 방식: /upload-template 결과의 id
    csv_template: str | None = None  # csv 방식: 태그가 든 CSV 텍스트
    groups: list[GroupIn]
    due: str | None = None
    notify: bool = False
    share_message: str | None = None


@router.post("/create-group-sheets")
async def create_group_sheets(req: CreateGroupSheetsRequest, sheets: SheetsClient = Depends(_sheets), drive: DriveClient = Depends(_drive)):
    groups = [usecases.GroupSpec(g.team_name, g.member_emails) for g in req.groups]
    try:
        return await usecases.create_group_sheets(
            sheets, drive, req.folder_id, req.activity_name, req.title_template, groups,
            template_spreadsheet_id=req.template_spreadsheet_id, csv_template=req.csv_template,
            due=req.due, notify=req.notify, share_message=req.share_message,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------- 유즈케이스 3 ----------


class CloseSubmissionRequest(BaseModel):
    spreadsheet_ids: list[str]
    to_role: str = "commenter"  # commenter | reader
    keep_emails: list[str] = []


@router.post("/close-submission")
async def close_submission(req: CloseSubmissionRequest, drive: DriveClient = Depends(_drive)):
    """마감 처리. Docs·Slides와 같은 함수. 이어서 /export/{id} 또는 /values/{id}."""
    return await usecases.close_submissions(drive, req.spreadsheet_ids, req.to_role, req.keep_emails)


class RestoreRequest(BaseModel):
    spreadsheet_id: str
    emails: list[str]


@router.post("/restore-edit-access")
async def restore_edit_access(req: RestoreRequest, drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.restore_editors(drive, req.spreadsheet_id, req.emails)
    except DriveApiError as e:
        raise _to_http(e)


@router.get("/permissions/{spreadsheet_id}")
async def permissions(spreadsheet_id: str, drive: DriveClient = Depends(_drive)):
    try:
        return await drive.list_permissions(spreadsheet_id)
    except DriveApiError as e:
        raise _to_http(e)


class LockRangesRequest(BaseModel):
    spreadsheet_id: str
    sheet_id: int
    cell_ranges: list[str]  # 예: ["B6:B9"]
    description: str = "마감"
    editor_emails: list[str] = []


@router.post("/lock-ranges")
async def lock_ranges(req: LockRangesRequest, sheets: SheetsClient = Depends(_sheets)):
    """유즈케이스 3의 선택지: 학생 입력 범위만 보호. 응답은 protectedRangeId 목록(해제에 필요)."""
    try:
        return await usecases.lock_ranges(sheets, req.spreadsheet_id, req.sheet_id, req.cell_ranges, req.description, req.editor_emails or None)
    except SheetsApiError as e:
        raise _to_http(e)


class UnlockRangesRequest(BaseModel):
    spreadsheet_id: str
    protected_range_ids: list[int]


@router.post("/unlock-ranges")
async def unlock_ranges(req: UnlockRangesRequest, sheets: SheetsClient = Depends(_sheets)):
    try:
        return await usecases.unlock_ranges(sheets, req.spreadsheet_id, req.protected_range_ids)
    except SheetsApiError as e:
        raise _to_http(e)


# ---------- 유즈케이스 4 ----------


@router.get("/export/{spreadsheet_id}")
async def export(spreadsheet_id: str, fmt: str = Query(default="xlsx"), drive: DriveClient = Depends(_drive)):
    try:
        exported = await usecases.export_spreadsheet(drive, spreadsheet_id, fmt)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except DriveApiError as e:
        raise _to_http(e)
    return Response(
        content=exported.content,
        media_type=exported.mime_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(exported.filename)}"},
    )


# ---------- 유즈케이스 5 ----------


@router.get("/values/{spreadsheet_id}")
async def values(
    spreadsheet_id: str,
    sheet_id: int | None = Query(default=None, description="불변 시트 ID(URL의 gid). 없으면 sheet_title, 둘 다 없으면 첫 시트"),
    sheet_title: str | None = Query(default=None),
    cell_range: str | None = Query(default=None, description="예: A5:C9. 없으면 시트 전체"),
    value_render_option: str = Query(default="UNFORMATTED_VALUE"),
    sheets: SheetsClient = Depends(_sheets),
):
    """마감 후 그룹 시트 값 읽기. DB 반영은 호출자(서비스 레포) 책임."""
    try:
        return await usecases.read_sheet_values(sheets, spreadsheet_id, sheet_id, sheet_title, cell_range, value_render_option)
    except SheetsApiError as e:
        raise _to_http(e)
