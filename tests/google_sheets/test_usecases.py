import pytest

from app.services.google_drive.client import SHEETS_EXPORT_MIME, DriveApiError
from app.services.google_sheets import usecases
from app.services.google_sheets.client import SheetsApiError
from app.services.google_sheets.usecases import GroupSpec, protect_range_requests, replace_tag_requests


class FakeDrive:
    """DriveClient 흉내. 네트워크 없이 create_group_sheets 흐름을 검사한다."""

    def __init__(self, fail_title: str | None = None):
        self.copied: list[dict] = []
        self.converted: list[dict] = []
        self.shared: list[tuple[str, str, str]] = []
        self.fail_title = fail_title

    def _new(self, name, parent):
        n = len(self.copied) + len(self.converted)
        return {"id": f"s-{n}", "name": name, "mimeType": "application/vnd.google-apps.spreadsheet", "parents": [parent]}

    async def copy_file(self, file_id, name, parent_folder_id=None):
        if name == self.fail_title:
            raise DriveApiError(404, {"error": {"message": "File not found", "errors": [{"reason": "notFound"}]}})
        self.copied.append({"source": file_id, "name": name, "parent": parent_folder_id})
        return self._new(name, parent_folder_id)

    async def create_from_content(self, name, content, source_mime_type, target_mime_type, parent_folder_id=None):
        self.converted.append({"name": name, "content": content, "source": source_mime_type, "target": target_mime_type, "parent": parent_folder_id})
        return self._new(name, parent_folder_id)

    async def share_with_user(self, file_id, email, role="reader", notify=False, message=None, expiration_time=None):
        self.shared.append((file_id, email, role))
        return {"id": f"perm-{email}", "role": role}

    async def get_file(self, file_id, fields=None):
        return {"id": file_id, "name": "평가표", "mimeType": "application/vnd.google-apps.spreadsheet"}

    async def export_file(self, file_id, mime_type):
        return b"PK"


class FakeSheets:
    def __init__(self, fail_id: str | None = None):
        self.updates: list[tuple[str, list[dict]]] = []
        self.fail_id = fail_id
        self.spreadsheet = {
            "spreadsheetId": "s-1",
            "properties": {"title": "평가표"},
            "sheets": [{"properties": {"sheetId": 77, "title": "역할 분담", "index": 1}}, {"properties": {"sheetId": 0, "title": "평가", "index": 0}}],
        }
        self.value_requests: list[str] = []

    async def batch_update(self, spreadsheet_id, requests, include_spreadsheet_in_response=False):
        if spreadsheet_id == self.fail_id:
            raise SheetsApiError(400, {"error": {"message": "bad", "status": "INVALID_ARGUMENT"}})
        self.updates.append((spreadsheet_id, requests))
        counts = {"{{team_name}}": 3, "{{activity_name}}": 1, "{{due}}": 0}
        replies = []
        for r in requests:
            if "findReplace" in r:
                replies.append({"findReplace": {"occurrencesChanged": counts[r["findReplace"]["find"]]}})
            elif "addProtectedRange" in r:
                replies.append({"addProtectedRange": {"protectedRange": {"protectedRangeId": 1000 + len(replies)}}})
            else:
                replies.append({})
        return {"spreadsheetId": spreadsheet_id, "replies": replies}

    async def get(self, spreadsheet_id, fields=None, ranges=None):
        return self.spreadsheet

    async def get_values(self, spreadsheet_id, a1_range, value_render_option="UNFORMATTED_VALUE", date_time_render_option="SERIAL_NUMBER", major_dimension="ROWS"):
        self.value_requests.append(a1_range)
        return {"range": a1_range, "values": [["항목", "점수"], ["출석", 10.0]]}


def test_replace_tag_requests_find_replace_all_sheets_match_case():
    reqs = replace_tag_requests({"team_name": "A조", "due": ""})
    assert reqs[0] == {"findReplace": {"find": "{{team_name}}", "replacement": "A조", "matchCase": True, "allSheets": True, "includeFormulas": True}}
    assert reqs[1]["findReplace"]["replacement"] == ""


def test_protect_range_requests_owner_only_by_default():
    reqs = protect_range_requests(0, ["B6:B9", "A:A"], "마감", None)
    assert len(reqs) == 2
    pr = reqs[0]["addProtectedRange"]["protectedRange"]
    assert pr["warningOnly"] is False and pr["editors"] == {"users": []} and pr["range"]["sheetId"] == 0 and pr["range"]["startRowIndex"] == 5  # 빈 users = 소유자만
    with_editors = protect_range_requests(0, ["B6"], "마감", ["ta@example.com"])[0]["addProtectedRange"]["protectedRange"]
    assert with_editors["editors"] == {"users": ["ta@example.com"]}


@pytest.mark.asyncio
async def test_create_group_sheets_copy_replace_share():
    drive, sheets = FakeDrive(), FakeSheets()
    results = await usecases.create_group_sheets(
        sheets, drive, folder_id="folder-1", activity_name="동료 평가 1차", title_template="{{activity_name}} - {{team_name}}",
        groups=[GroupSpec("A조", ["a1@example.com"]), GroupSpec("B조")], template_spreadsheet_id="tpl", due=None,
    )
    assert [c["name"] for c in drive.copied] == ["동료 평가 1차 - A조", "동료 평가 1차 - B조"]
    assert all(c["source"] == "tpl" and c["parent"] == "folder-1" for c in drive.copied)
    assert len(sheets.updates) == 2 and drive.converted == []  # 그룹당 batchUpdate 1회
    a, b = results
    assert a.document and a.document.id == "s-1" and a.document.title == "동료 평가 1차 - A조"
    assert a.replaced == {"team_name": 3, "activity_name": 1, "due": 0}
    assert [(s.email, s.ok) for s in a.shares] == [("a1@example.com", True)]
    assert drive.shared == [("s-1", "a1@example.com", "writer")]
    assert b.shares == [] and b.error is None


@pytest.mark.asyncio
async def test_create_group_sheets_csv_method_renders_tags_without_sheets_calls():
    drive, sheets = FakeDrive(), FakeSheets()
    results = await usecases.create_group_sheets(
        sheets, drive, "folder-1", "평가", "{{team_name}}", [GroupSpec("A조", ["a@example.com"])],
        csv_template="팀,{{team_name}}\n마감,{{due}}\n항목,점수\n", due="10/10",
    )
    assert drive.copied == [] and sheets.updates == []
    assert drive.converted[0]["content"] == "팀,A조\n마감,10/10\n항목,점수\n"
    assert drive.converted[0]["source"] == "text/csv" and drive.converted[0]["target"] == "application/vnd.google-apps.spreadsheet"
    assert results[0].replaced == {} and results[0].shares[0].ok


@pytest.mark.asyncio
async def test_create_group_sheets_requires_exactly_one_template():
    with pytest.raises(ValueError):
        await usecases.create_group_sheets(FakeSheets(), FakeDrive(), "f", "a", "t", [GroupSpec("A")])
    with pytest.raises(ValueError):
        await usecases.create_group_sheets(FakeSheets(), FakeDrive(), "f", "a", "t", [GroupSpec("A")], template_spreadsheet_id="x", csv_template="y")


@pytest.mark.asyncio
async def test_create_group_sheets_continues_after_copy_or_replace_failure():
    drive, sheets = FakeDrive(fail_title="평가 - A조"), FakeSheets(fail_id="s-1")
    results = await usecases.create_group_sheets(
        sheets, drive, "folder-1", "평가", "{{activity_name}} - {{team_name}}",
        [GroupSpec("A조", ["a@example.com"]), GroupSpec("B조", ["b@example.com"]), GroupSpec("C조")], template_spreadsheet_id="tpl",
    )
    a, b, c = results
    assert a.document is None and "notFound" in a.error
    assert b.document and b.document.id == "s-1" and "INVALID_ARGUMENT" in b.error and b.shares == []  # 복사본은 남는다
    assert c.error is None and c.document.id == "s-2"
    assert drive.shared == []  # 치환 실패한 B조는 공유하지 않는다


@pytest.mark.asyncio
async def test_read_sheet_values_by_sheet_id_resolves_current_title():
    sheets = FakeSheets()
    sv = await usecases.read_sheet_values(sheets, "s-1", sheet_id=77, cell_range="A1:B2")
    assert sv.sheet_title == "역할 분담" and sheets.value_requests == ["'역할 분담'!A1:B2"] and sv.values[1] == ["출석", 10.0]
    first = await usecases.read_sheet_values(sheets, "s-1")
    assert first.sheet_id == 0 and first.sheet_title == "평가"  # index 기준 첫 시트
    with pytest.raises(SheetsApiError):
        await usecases.read_sheet_values(sheets, "s-1", sheet_id=999)


@pytest.mark.asyncio
async def test_lock_ranges_returns_protected_range_ids():
    sheets = FakeSheets()
    ids = await usecases.lock_ranges(sheets, "s-1", 0, ["B6:B9", "C6:C9"], "마감")
    assert ids == [1000, 1001] and len(sheets.updates) == 1  # batchUpdate 1회


@pytest.mark.asyncio
async def test_export_spreadsheet_formats():
    exported = await usecases.export_spreadsheet(FakeDrive(), "s", fmt="xlsx")
    assert exported.filename == "평가표.xlsx" and exported.mime_type == SHEETS_EXPORT_MIME["xlsx"]
    with pytest.raises(ValueError):
        await usecases.export_spreadsheet(FakeDrive(), "s", fmt="docx")


@pytest.mark.asyncio
async def test_list_sheets_sorted_by_index_with_protected_ranges():
    sheets = FakeSheets()
    sheets.spreadsheet["sheets"][0]["protectedRanges"] = [{"protectedRangeId": 5, "range": {"sheetId": 77}}]
    infos = await usecases.list_sheets(sheets, "s-1")
    assert [(i.sheet_id, i.title, i.index) for i in infos] == [(0, "평가", 0), (77, "역할 분담", 1)]
    assert infos[1].protected_ranges[0]["protectedRangeId"] == 5 and infos[0].protected_ranges == []
