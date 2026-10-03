import pytest

from app.services.google_drive.client import SLIDES_EXPORT_MIME, DriveApiError
from app.services.google_slides import usecases
from app.services.google_slides.client import SlidesApiError
from app.services.google_slides.usecases import GroupSpec, replace_tag_requests


class FakeDrive:
    """DriveClient 흉내. 네트워크 없이 create_group_presentations 흐름을 검사한다."""

    def __init__(self, fail_copy_title: str | None = None):
        self.copied: list[dict] = []
        self.shared: list[tuple[str, str, str]] = []
        self.fail_copy_title = fail_copy_title

    async def copy_file(self, file_id, name, parent_folder_id=None):
        if name == self.fail_copy_title:
            raise DriveApiError(404, {"error": {"message": "File not found", "errors": [{"reason": "notFound"}]}})
        self.copied.append({"source": file_id, "name": name, "parent": parent_folder_id})
        return {"id": f"p-{len(self.copied)}", "name": name, "mimeType": "application/vnd.google-apps.presentation", "parents": [parent_folder_id]}

    async def share_with_user(self, file_id, email, role="reader", notify=False, message=None, expiration_time=None):
        self.shared.append((file_id, email, role))
        return {"id": f"perm-{email}", "role": role}

    async def get_file(self, file_id, fields=None):
        return {"id": file_id, "name": "발표"}

    async def export_file(self, file_id, mime_type):
        return b"PK"


class FakeSlides:
    def __init__(self, fail_id: str | None = None):
        self.updates: list[tuple[str, list[dict]]] = []
        self.fail_id = fail_id

    async def batch_update(self, presentation_id, requests, required_revision_id=None):
        if presentation_id == self.fail_id:
            raise SlidesApiError(400, {"error": {"message": "bad", "status": "INVALID_ARGUMENT"}})
        self.updates.append((presentation_id, requests))
        # due 태그는 템플릿에 없다고 가정 → 0
        counts = {"{{team_name}}": 2, "{{activity_name}}": 1, "{{due}}": 0}
        return {"replies": [{"replaceAllText": {"occurrencesChanged": counts[r["replaceAllText"]["containsText"]["text"]]}} for r in requests]}


def test_replace_tag_requests_exact_tag_and_match_case():
    reqs = replace_tag_requests({"team_name": "A조", "due": ""})
    assert reqs[0] == {"replaceAllText": {"containsText": {"text": "{{team_name}}", "matchCase": True}, "replaceText": "A조"}}
    assert reqs[1]["replaceAllText"]["replaceText"] == ""


@pytest.mark.asyncio
async def test_create_group_presentations_copy_replace_share():
    drive, slides = FakeDrive(), FakeSlides()
    results = await usecases.create_group_presentations(
        slides, drive, folder_id="folder-1", activity_name="발표1", title_template="{{activity_name}} - {{team_name}}",
        template_presentation_id="tpl", groups=[GroupSpec("A조", ["a1@example.com"]), GroupSpec("B조")], due=None,
    )
    assert [c["name"] for c in drive.copied] == ["발표1 - A조", "발표1 - B조"]
    assert all(c["source"] == "tpl" and c["parent"] == "folder-1" for c in drive.copied)
    assert len(slides.updates) == 2  # 그룹당 batchUpdate 1회
    a, b = results
    assert a.document and a.document.id == "p-1" and a.document.title == "발표1 - A조"
    assert a.replaced == {"team_name": 2, "activity_name": 1, "due": 0}
    assert [(s.email, s.ok) for s in a.shares] == [("a1@example.com", True)]
    assert drive.shared == [("p-1", "a1@example.com", "writer")]
    assert b.shares == [] and b.error is None


@pytest.mark.asyncio
async def test_create_group_presentations_continues_after_copy_or_replace_failure():
    drive, slides = FakeDrive(fail_copy_title="발표1 - A조"), FakeSlides(fail_id="p-1")
    results = await usecases.create_group_presentations(
        slides, drive, "folder-1", "발표1", "{{activity_name}} - {{team_name}}", "tpl",
        [GroupSpec("A조", ["a@example.com"]), GroupSpec("B조", ["b@example.com"]), GroupSpec("C조")],
    )
    a, b, c = results
    assert a.document is None and "notFound" in a.error
    assert b.document and b.document.id == "p-1" and "INVALID_ARGUMENT" in b.error and b.shares == []  # 복사본은 남는다
    assert c.error is None and c.document.id == "p-2"
    assert drive.shared == []  # 치환 실패한 B조는 공유하지 않는다


@pytest.mark.asyncio
async def test_export_presentation_formats():
    exported = await usecases.export_presentation(FakeDrive(), "p", fmt="pptx")
    assert exported.filename == "발표.pptx" and exported.mime_type == SLIDES_EXPORT_MIME["pptx"]
    with pytest.raises(ValueError):
        await usecases.export_presentation(FakeDrive(), "p", fmt="docx")
