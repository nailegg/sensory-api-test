import pytest

from app.core.models import DocumentKind
from app.services.google_sheets.mapper import (
    a1,
    column_index,
    column_letter,
    document_from_spreadsheet,
    first_sheet_title,
    grid_range,
    plain_text,
    quote_sheet_title,
    sheet_titles,
)

SPREADSHEET = {
    "spreadsheetId": "s-1",
    "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/s-1/edit",
    "properties": {"title": "동료 평가", "locale": "ko_KR", "timeZone": "Asia/Seoul"},
    "sheets": [
        {"properties": {"sheetId": 77, "title": "역할 분담", "index": 1}},
        {"properties": {"sheetId": 0, "title": "평가", "index": 0}},
    ],
}


def test_column_letter_and_index_roundtrip():
    assert [column_letter(i) for i in (0, 25, 26, 27, 701, 702)] == ["A", "Z", "AA", "AB", "ZZ", "AAA"]
    assert [column_index(c) for c in ("A", "Z", "AA", "AB", "ZZ", "AAA")] == [0, 25, 26, 27, 701, 702]
    with pytest.raises(ValueError):
        column_index("A1")


def test_a1_quotes_sheet_title():
    assert quote_sheet_title("평가") == "'평가'"
    assert quote_sheet_title("A조's 시트") == "'A조''s 시트'"
    assert a1("팀 A", "B6:B9") == "'팀 A'!B6:B9"
    assert a1("팀 A") == "'팀 A'"


def test_grid_range_half_open_zero_based():
    assert grid_range(0, "B6:B9") == {"sheetId": 0, "startColumnIndex": 1, "endColumnIndex": 2, "startRowIndex": 5, "endRowIndex": 9}
    assert grid_range(5, "C5") == {"sheetId": 5, "startColumnIndex": 2, "endColumnIndex": 3, "startRowIndex": 4, "endRowIndex": 5}
    assert grid_range(0, "A:B") == {"sheetId": 0, "startColumnIndex": 0, "endColumnIndex": 2}  # 행 무한
    assert grid_range(0, "2:2") == {"sheetId": 0, "startRowIndex": 1, "endRowIndex": 2}  # 열 무한
    with pytest.raises(ValueError):
        grid_range(0, "")
    with pytest.raises(ValueError):
        grid_range(0, "A1:B2:C3")


def test_sheet_titles_and_first_sheet_by_index():
    assert sheet_titles(SPREADSHEET) == {77: "역할 분담", 0: "평가"}
    assert first_sheet_title(SPREADSHEET) == "평가"
    assert first_sheet_title({"sheets": []}) is None


def test_plain_text_tab_rows_and_sheet_labels():
    value_ranges = [
        {"range": "'평가'!A1:C3", "values": [["항목", "점수"], ["출석", 10.0], ["과제", 7.5, True]]},
        {"range": "'역할 분담'!A1:B1", "values": [["이름", None]]},
    ]
    assert plain_text(value_ranges) == "[평가]\n항목\t점수\n출석\t10\n과제\t7.5\tTRUE\n\n[역할 분담]\n이름\t"


def test_document_from_spreadsheet_merges_drive_meta():
    drive_file = {
        "id": "s-1",
        "name": "drive 이름",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "webViewLink": "https://docs.google.com/spreadsheets/d/s-1/edit?usp=drivesdk",
        "owners": [{"displayName": "Tester"}],
        "parents": ["folder-1"],
    }
    d = document_from_spreadsheet(SPREADSHEET, drive_file, text="[평가]\n")
    assert d.kind == DocumentKind.SHEET and d.title == "동료 평가" and d.owner == "Tester" and d.parent_folder_id == "folder-1"
    assert d.url.endswith("usp=drivesdk") and d.text == "[평가]\n"


def test_document_from_spreadsheet_without_drive_uses_spreadsheet_url():
    d = document_from_spreadsheet(SPREADSHEET)
    assert d.id == "s-1" and d.kind == DocumentKind.SHEET and d.url == SPREADSHEET["spreadsheetUrl"] and d.owner is None
