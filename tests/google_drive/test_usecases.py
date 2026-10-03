import pytest

from app.services.google_drive import usecases
from app.services.google_drive.client import DriveApiError
from app.services.google_drive.usecases import GroupSpec


class FakeDrive:
    """DriveClient 흉내. create_group_files_from_template의 복사 → 치환 → 공유 흐름만 검사한다."""

    def __init__(self, invisible_template: str | None = None):
        self.copied: list[dict] = []
        self.shared: list[tuple[str, str, str]] = []
        self.invisible_template = invisible_template  # Picker로 고르지 않은(앱이 못 보는) 템플릿 → 404

    async def copy_file(self, file_id, name, parent_folder_id=None):
        if file_id == self.invisible_template:
            raise DriveApiError(404, {"error": {"message": f"File not found: {file_id}.", "errors": [{"reason": "notFound"}]}})
        self.copied.append({"source": file_id, "name": name, "parent": parent_folder_id})
        return {"id": f"copy-{len(self.copied)}", "name": name, "mimeType": "application/vnd.google-apps.spreadsheet", "parents": [parent_folder_id]}

    async def share_with_user(self, file_id, email, role="reader", notify=False, message=None, expiration_time=None):
        self.shared.append((file_id, email, role))
        return {"id": f"perm-{email}", "role": role}


class ReplaceFailed(Exception):
    pass


@pytest.mark.asyncio
async def test_copy_replace_share_calls_replace_with_copy_id_and_variables():
    drive = FakeDrive()
    calls: list[tuple[str, dict]] = []

    async def replace(file_id, variables):
        calls.append((file_id, variables))
        return {"team_name": 2, "due": 0}

    results = await usecases.create_group_files_from_template(
        drive, "folder-1", "과제1", "{{activity_name}} - {{team_name}}", "tpl", [GroupSpec("A조", ["a@example.com"]), GroupSpec("B조")],
        replace_tags=replace, due="2026-10-10",
    )
    assert [c["name"] for c in drive.copied] == ["과제1 - A조", "과제1 - B조"]
    assert all(c["source"] == "tpl" and c["parent"] == "folder-1" for c in drive.copied)  # 원본은 건드리지 않고 복사본만
    assert calls == [("copy-1", {"team_name": "A조", "activity_name": "과제1", "due": "2026-10-10"}), ("copy-2", {"team_name": "B조", "activity_name": "과제1", "due": "2026-10-10"})]
    a, b = results
    assert a.document.id == "copy-1" and a.replaced == {"team_name": 2, "due": 0} and [(s.email, s.ok) for s in a.shares] == [("a@example.com", True)]
    assert b.shares == [] and b.error is None


@pytest.mark.asyncio
async def test_template_not_visible_to_app_gives_404_per_group_and_no_copy():
    drive = FakeDrive(invisible_template="picked-but-not-via-picker")

    async def replace(file_id, variables):
        raise AssertionError("복사가 안 됐으면 치환을 부르지 않는다")

    results = await usecases.create_group_files_from_template(
        drive, "folder-1", "과제1", "{{team_name}}", "picked-but-not-via-picker", [GroupSpec("A조", ["a@example.com"])], replace_tags=replace,
    )
    assert results[0].document is None and "404 notFound" in results[0].error
    assert drive.copied == [] and drive.shared == []


@pytest.mark.asyncio
async def test_replace_failure_of_listed_type_keeps_copy_and_skips_share_but_other_exceptions_propagate():
    drive = FakeDrive()

    async def replace(file_id, variables):
        if file_id == "copy-1":
            raise ReplaceFailed("bad tag")
        return {"team_name": 1}

    results = await usecases.create_group_files_from_template(
        drive, "f", "과제1", "{{team_name}}", "tpl", [GroupSpec("A조", ["a@example.com"]), GroupSpec("B조", ["b@example.com"])],
        replace_tags=replace, replace_errors=(ReplaceFailed,),
    )
    a, b = results
    assert a.document.id == "copy-1" and "bad tag" in a.error and a.shares == []  # 복사본은 남고 공유는 안 한다
    assert b.error is None and drive.shared == [("copy-2", "b@example.com", "writer")]

    async def boom(file_id, variables):
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        await usecases.create_group_files_from_template(FakeDrive(), "f", "x", "{{team_name}}", "tpl", [GroupSpec("A조")], replace_tags=boom, replace_errors=(ReplaceFailed,))
