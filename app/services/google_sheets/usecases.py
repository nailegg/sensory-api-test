"""Sheets 시나리오 흐름. 여러 client와 mapper를 엮는다. FastAPI를 import하지 않는다.

유즈케이스(docs/google_sheets.md 1절, 2026-10-04 확정: Docs·Slides와 같은 4개 + 마감 후 값 읽기):
1. 액티비티 폴더 생성 → google_drive.usecases.create_folder
2. 템플릿으로 그룹마다 스프레드시트 생성 + 그룹원 편집 권한 → upload_template(액티비티당 1회) + create_group_sheets
3. 마감 시 편집 비활성화 → close_submissions (google_drive.usecases, Docs·Slides와 같은 함수).
   선택지: lock_ranges로 학생 입력 열만 보호(파일은 열어 둠)
4. 마감 시 파일로 내보내기 → export_spreadsheet (xlsx | pdf | csv | ods | tsv | zip)
5. 마감 후 그룹 시트 값 읽기 → read_sheet_values (Synsory DB 반영은 호출자 책임)

성적표 동기화(create_gradebook 등)는 검토 후 보류(1.3절). 여기 없다.
"""

from dataclasses import dataclass, field

from app.core.models import Document
from app.services.google_drive.client import (
    MIME_CSV,
    MIME_SHEET,
    MIME_XLSX,
    SHEETS_EXPORT_MIME,
    DriveApiError,
    DriveClient,
)
from app.services.google_drive.mapper import document_from_drive_file

# 유즈케이스 2 공유 · 3 · 4는 Drive 호출뿐이라 Docs·Slides와 같은 함수를 쓴다.
from app.services.google_drive.usecases import (  # noqa: F401
    CloseResult,
    ExportedFile,
    GroupSpec,
    ShareResult,
    close_submissions,
    downgrade_editors,
    export_file,
    group_variables,
    render_template,
    restore_editors,
    share_file,
)
from app.services.google_sheets.client import SheetsApiError, SheetsClient
from app.services.google_sheets.mapper import a1, document_from_spreadsheet, grid_range, plain_text, sheet_titles

# ---------- 읽기·생성 배관 ----------


async def read_spreadsheet(sheets: SheetsClient, drive: DriveClient, spreadsheet_id: str, include_values: bool = False) -> Document:
    """구조(시트 목록) + Drive 메타데이터 → Document. include_values면 모든 시트 값을 평문(text)으로 붙인다.
    호출 수: get 1 + Drive 1 (+ values.batchGet 1)."""
    spreadsheet = await sheets.get(spreadsheet_id)
    drive_file = await drive.get_file(spreadsheet_id)
    text = None
    if include_values:
        titles = sheet_titles(spreadsheet)
        if titles:
            data = await sheets.batch_get_values(spreadsheet_id, [a1(t) for t in titles.values()])
            text = plain_text(data.get("valueRanges", []))
    return document_from_spreadsheet(spreadsheet, drive_file, text=text)


async def create_empty_spreadsheet(
    sheets: SheetsClient, drive: DriveClient, title: str, folder_id: str | None = None, sheet_names: list[str] | None = None
) -> Document:
    """빈 스프레드시트 생성 → (선택) 폴더로 이동 → Document. spreadsheets.create는 폴더를 못 정하므로 Drive로 옮긴다(호출 2회).
    폴더만 필요하고 시트 구성이 필요 없으면 Drive files.create(mimeType=spreadsheet) 1회가 더 싸다."""
    spreadsheet = await sheets.create(title, sheet_names)
    spreadsheet_id = spreadsheet["spreadsheetId"]
    drive_file = await drive.move_file(spreadsheet_id, to_folder_id=folder_id) if folder_id else await drive.get_file(spreadsheet_id)
    return document_from_spreadsheet(spreadsheet, drive_file)


@dataclass
class SheetInfo:
    sheet_id: int  # 불변. URL의 gid. 서비스는 이름이 아니라 이 값을 저장한다
    title: str
    index: int
    hidden: bool = False
    row_count: int | None = None
    column_count: int | None = None
    frozen_row_count: int = 0
    protected_ranges: list[dict] = field(default_factory=list)  # protectedRangeId·range·description·editors


async def list_sheets(sheets: SheetsClient, spreadsheet_id: str) -> list[SheetInfo]:
    """시트 목록(sheetId·이름·크기·보호 범위). spreadsheets.get 1회. 변환 업로드·복사된 파일의 sheetId는 0이 아닐 수 있으므로
    보호 범위·sheet_id 기반 읽기 전에 여기서 확인한다."""
    spreadsheet = await sheets.get(spreadsheet_id)
    out: list[SheetInfo] = []
    for s in sorted(spreadsheet.get("sheets", []), key=lambda s: s.get("properties", {}).get("index", 0)):
        p = s.get("properties", {})
        grid = p.get("gridProperties", {})
        out.append(SheetInfo(
            sheet_id=p["sheetId"], title=p.get("title", ""), index=p.get("index", 0), hidden=bool(p.get("hidden", False)),
            row_count=grid.get("rowCount"), column_count=grid.get("columnCount"), frozen_row_count=grid.get("frozenRowCount", 0),
            protected_ranges=s.get("protectedRanges", []),
        ))
    return out


# ---------- 유즈케이스 5: 값 읽기 ----------


@dataclass
class SheetValues:
    spreadsheet_id: str
    sheet_id: int | None
    sheet_title: str
    range: str  # 실제 응답 범위(A1). 뒤쪽 빈 행·열은 잘려 있다
    values: list[list]  # UNFORMATTED_VALUE: 숫자는 숫자, 날짜는 일련번호, 빈 셀은 "" 또는 행 끝에서 생략


async def read_sheet_values(
    sheets: SheetsClient,
    spreadsheet_id: str,
    sheet_id: int | None = None,
    sheet_title: str | None = None,
    cell_range: str | None = None,
    value_render_option: str = "UNFORMATTED_VALUE",
) -> SheetValues:
    """시트 하나의 값을 2차원 배열로. sheet_id(불변)로 지정하면 spreadsheets.get으로 현재 이름을 찾아 A1을 만든다(호출 2회).
    sheet_title로 지정하면 1회. 둘 다 없으면 첫 시트. 유효성(숫자 범위·빈 칸)과 DB 반영은 호출자 책임."""
    if sheet_title is None or sheet_id is None:
        spreadsheet = await sheets.get(spreadsheet_id)
        titles = sheet_titles(spreadsheet)
        if sheet_id is not None:
            if sheet_id not in titles:
                raise SheetsApiError(404, {"error": {"message": f"sheetId {sheet_id} not in spreadsheet", "status": "NOT_FOUND"}})
            sheet_title = titles[sheet_id]
        elif sheet_title is not None:
            sheet_id = next((sid for sid, t in titles.items() if t == sheet_title), None)
        else:
            first = min(spreadsheet.get("sheets", []), key=lambda s: s["properties"].get("index", 0))
            sheet_id, sheet_title = first["properties"]["sheetId"], first["properties"]["title"]
    data = await sheets.get_values(spreadsheet_id, a1(sheet_title, cell_range), value_render_option=value_render_option)
    return SheetValues(
        spreadsheet_id=spreadsheet_id,
        sheet_id=sheet_id,
        sheet_title=sheet_title,
        range=data.get("range", ""),
        values=data.get("values", []),
    )


async def write_values(
    sheets: SheetsClient, spreadsheet_id: str, sheet_title: str, cell_range: str, values: list[list], value_input_option: str = "RAW"
) -> dict:
    """배관·실험용: 범위 하나 덮어쓰기(values.update 1회). RAW 기본(학번 앞자리 0 유지). 수식·날짜 인식은 USER_ENTERED."""
    return await sheets.update_values(spreadsheet_id, a1(sheet_title, cell_range), values, value_input_option)


# ---------- 유즈케이스 2 ----------


async def upload_template(drive: DriveClient, name: str, xlsx: bytes, folder_id: str | None = None) -> Document:
    """Synsory가 보관하는 xlsx 템플릿을 교수자 Drive에 Sheets로 변환 업로드한다(액티비티당 1회).
    앱이 만든 파일이 되므로 drive.file로 files.copy 원본이 될 수 있다. 템플릿 안의 태그는 `{{team_name}}`처럼 공백 없이 쓴다."""
    drive_file = await drive.create_from_content(name, xlsx, MIME_XLSX, MIME_SHEET, folder_id)
    return document_from_drive_file(drive_file)


def replace_tag_requests(variables: dict[str, str], include_formulas: bool = True) -> list[dict]:
    """`{{key}}` → 값 치환 요청(findReplace, allSheets). 태그 개수와 무관하게 batchUpdate 1회에 담는다(쓰기 쿼터 1).
    matchCase=true로 오타 태그에 걸리지 않게 한다. include_formulas=true면 `="{{team_name}} 합계"` 같은 수식 안 태그도 바꾼다.
    응답 occurrencesChanged로 템플릿 문제를 찾는다."""
    return [
        {
            "findReplace": {
                "find": f"{{{{{key}}}}}",
                "replacement": value,
                "matchCase": True,
                "allSheets": True,
                "includeFormulas": include_formulas,
            }
        }
        for key, value in variables.items()
    ]


async def replace_tags(sheets: SheetsClient, spreadsheet_id: str, variables: dict[str, str]) -> dict[str, int]:
    """스프레드시트 전체(모든 시트)에서 태그를 치환하고 태그별 치환 횟수를 돌려준다. 0이면 템플릿에 그 태그가 없는 것."""
    resp = await sheets.batch_update(spreadsheet_id, replace_tag_requests(variables))
    replies = resp.get("replies", [])
    return {
        key: (replies[i].get("findReplace", {}).get("occurrencesChanged", 0) if i < len(replies) else 0)
        for i, key in enumerate(variables)
    }


@dataclass
class GroupSheetResult:
    team_name: str
    document: Document | None
    replaced: dict[str, int] = field(default_factory=dict)  # 태그별 치환 횟수 (copy 방식에서만)
    shares: list[ShareResult] = field(default_factory=list)
    error: str | None = None


async def create_group_sheets(
    sheets: SheetsClient,
    drive: DriveClient,
    folder_id: str,
    activity_name: str,
    title_template: str,
    groups: list[GroupSpec],
    template_spreadsheet_id: str | None = None,
    csv_template: str | None = None,
    due: str | None = None,
    notify: bool = False,
    share_message: str | None = None,
) -> list[GroupSheetResult]:
    """그룹마다 스프레드시트를 폴더 안에 만들고 그룹원에게 편집 권한을 준다. 두 방식 중 하나:

    - copy(기본): template_spreadsheet_id(upload_template 결과)를 Drive files.copy → Sheets findReplace로 태그 치환.
      그룹당 Drive 1 + Sheets 1 + 그룹원 수. 데이터 검증·수식·서식·시트 구성이 복사본에 그대로 남는다.
    - csv: csv_template의 태그를 텍스트 치환해 그룹마다 Drive 변환 업로드. 그룹당 Drive 1 + 그룹원 수. Sheets 호출 없음.
      값만 있는 표라면 가장 단순하지만 서식·검증·수식·시트 여러 장은 못 넣는다(Docs의 Markdown 방식에 대응).

    한 그룹이 실패해도 다음 그룹을 계속 만들고, 결과에 error를 담아 돌려준다.
    복사는 됐는데 치환이 실패하면 document와 error가 함께 담긴다(파일은 남아 있으니 호출자가 정리하거나 재시도).
    """
    if (template_spreadsheet_id is None) == (csv_template is None):
        raise ValueError("template_spreadsheet_id(copy 방식)와 csv_template(csv 방식) 중 하나만 지정한다")
    results: list[GroupSheetResult] = []
    for group in groups:
        variables = group_variables(group.team_name, activity_name, due)
        title = render_template(title_template, variables)
        replaced: dict[str, int] = {}
        try:
            if csv_template is not None:
                csv_text = render_template(csv_template, variables)
                drive_file = await drive.create_from_content(title, csv_text, MIME_CSV, MIME_SHEET, folder_id)
            else:
                drive_file = await drive.copy_file(template_spreadsheet_id, title, folder_id)
            document = document_from_drive_file(drive_file)
        except DriveApiError as e:
            results.append(GroupSheetResult(team_name=group.team_name, document=None, error=str(e)))
            continue
        if template_spreadsheet_id is not None:
            try:
                replaced = await replace_tags(sheets, document.id, variables)
            except SheetsApiError as e:
                results.append(GroupSheetResult(team_name=group.team_name, document=document, error=str(e)))
                continue
        shares = await share_file(drive, document.id, group.member_emails, notify=notify, message=share_message)
        results.append(GroupSheetResult(team_name=group.team_name, document=document, replaced=replaced, shares=shares))
    return results


# ---------- 유즈케이스 3 ----------
# close_submissions · downgrade_editors · restore_editors → google_drive.usecases (위에서 다시 내보냄)


def protect_range_requests(sheet_id: int, cell_ranges: list[str], description: str, editor_emails: list[str] | None = None) -> list[dict]:
    """addProtectedRange 요청. **editors를 항상 명시한다.** 실측(2026-10-04): editors를 생략하면 Sheets가 "현재 문서 편집자 전원"
    (학생 writer 포함)을 편집 가능으로 넣어 보호가 아무도 막지 못한다. `users: []`로 보내야 소유자(요청자)만 남는다.
    editor_emails(조교 등)를 주면 그 사람들 + 소유자. 보호는 UI 편집만 막고 보기는 못 막으며, 소유자 토큰의 API 쓰기도 막지 않는다(10절)."""
    protected: dict = {"description": description, "warningOnly": False, "editors": {"users": list(editor_emails or [])}}
    return [{"addProtectedRange": {"protectedRange": {**protected, "range": grid_range(sheet_id, r)}}} for r in cell_ranges]


async def lock_ranges(
    sheets: SheetsClient, spreadsheet_id: str, sheet_id: int, cell_ranges: list[str], description: str = "마감", editor_emails: list[str] | None = None
) -> list[int]:
    """유즈케이스 3의 선택지: 파일은 열어 두고 학생 입력 범위만 보호한다. batchUpdate 1회. 돌려주는 protectedRangeId로 해제한다."""
    resp = await sheets.batch_update(spreadsheet_id, protect_range_requests(sheet_id, cell_ranges, description, editor_emails))
    return [r["addProtectedRange"]["protectedRange"]["protectedRangeId"] for r in resp.get("replies", [])]


async def unlock_ranges(sheets: SheetsClient, spreadsheet_id: str, protected_range_ids: list[int]) -> dict:
    """보호 해제(마감 연장). batchUpdate 1회."""
    return await sheets.batch_update(spreadsheet_id, [{"deleteProtectedRange": {"protectedRangeId": pid}} for pid in protected_range_ids])


# ---------- 유즈케이스 4 ----------


async def export_spreadsheet(drive: DriveClient, spreadsheet_id: str, fmt: str = "xlsx") -> ExportedFile:
    """files.export. xlsx | pdf | csv | ods | tsv | zip. csv·tsv는 첫 시트만. 결과는 10MB까지."""
    return await export_file(drive, spreadsheet_id, fmt, SHEETS_EXPORT_MIME)
