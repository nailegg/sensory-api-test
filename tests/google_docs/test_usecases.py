import pytest

from app.services.google_docs import usecases
from app.services.google_docs.usecases import GroupSpec, render_template
from app.services.google_drive.client import DriveApiError


def test_render_template_replaces_known_and_keeps_unknown():
    out = render_template("# {{activity_name}}\n팀 {{ team_name }} / {{unknown}} / {x}", {"activity_name": "과제1", "team_name": "A조"})
    assert out == "# 과제1\n팀 A조 / {{unknown}} / {x}"


class FakeDrive:
    """DriveClient 흉내. 네트워크 없이 create_group_documents 흐름을 검사한다."""

    def __init__(self, fail_email: str | None = None):
        self.created: list[dict] = []
        self.shared: list[tuple[str, str, str]] = []
        self.fail_email = fail_email

    async def create_from_content(self, name, content, source_mime_type, target_mime_type, parent_folder_id):
        self.created.append({"name": name, "content": content, "parent": parent_folder_id})
        return {"id": f"id-{len(self.created)}", "name": name, "mimeType": target_mime_type, "parents": [parent_folder_id]}

    async def list_permissions(self, file_id):
        if file_id == "missing":
            raise DriveApiError(404, {"error": {"message": "File not found", "errors": [{"reason": "notFound"}]}})
        return [
            {"id": "p-owner", "type": "user", "role": "owner", "emailAddress": "prof@example.com"},
            {"id": "p-ta", "type": "user", "role": "writer", "emailAddress": "TA@example.com"},
            {"id": "p-s1", "type": "user", "role": "writer", "emailAddress": "s1@example.com"},
            {"id": "p-s2", "type": "user", "role": "commenter", "emailAddress": "s2@example.com"},
        ]

    async def update_permission_role(self, file_id, permission_id, role):
        self.updated = getattr(self, "updated", []) + [(permission_id, role)]
        return {"id": permission_id, "role": role}

    async def share_with_user(self, file_id, email, role="reader", notify=False, message=None, expiration_time=None):
        if email == self.fail_email:
            raise DriveApiError(400, {"error": {"message": "Invalid email", "errors": [{"reason": "invalidSharingRequest"}]}})
        self.shared.append((file_id, email, role))
        return {"id": f"perm-{email}", "role": role}


@pytest.mark.asyncio
async def test_create_group_documents_markdown_flow_with_partial_share_failure():
    drive = FakeDrive(fail_email="bad@example.com")
    groups = [GroupSpec("A조", ["a1@example.com", "bad@example.com"]), GroupSpec("B조", ["b1@example.com"])]
    results = await usecases.create_group_documents(
        docs=None, drive=drive, folder_id="folder-1", activity_name="과제1",
        title_template="{{activity_name}} - {{team_name}}", body_template="# {{activity_name}}\n\n팀: {{team_name}}\n마감: {{due}}",
        groups=groups, due="2026-10-10",
    )
    assert [c["name"] for c in drive.created] == ["과제1 - A조", "과제1 - B조"]
    assert drive.created[0]["content"] == "# 과제1\n\n팀: A조\n마감: 2026-10-10"
    assert all(c["parent"] == "folder-1" for c in drive.created)

    a, b = results
    assert a.document and a.document.id == "id-1" and a.document.title == "과제1 - A조"
    assert [(s.email, s.ok) for s in a.shares] == [("a1@example.com", True), ("bad@example.com", False)]
    assert "invalidSharingRequest" in a.shares[1].error
    assert b.document and [(s.email, s.ok) for s in b.shares] == [("b1@example.com", True)]
    assert all(role == "writer" for _, _, role in drive.shared)


@pytest.mark.asyncio
async def test_export_rejects_unknown_format():
    with pytest.raises(ValueError):
        await usecases.export_document(FakeDrive(), "x", fmt="exe")


@pytest.mark.asyncio
async def test_downgrade_editors_skips_owner_and_keep_emails_case_insensitive():
    drive = FakeDrive()
    changed = await usecases.downgrade_editors(drive, "doc", to_role="commenter", keep_emails=["ta@example.com"])
    assert drive.updated == [("p-s1", "commenter")]
    assert changed == [{"id": "p-s1", "role": "commenter"}]


@pytest.mark.asyncio
async def test_restore_editors_only_targets_listed_non_writers():
    drive = FakeDrive()
    await usecases.restore_editors(drive, "doc", ["s2@example.com", "s1@example.com"])
    assert drive.updated == [("p-s2", "writer")]  # s1은 이미 writer라 건너뜀


@pytest.mark.asyncio
async def test_close_submissions_continues_after_failure():
    drive = FakeDrive()
    results = await usecases.close_submissions(drive, ["doc-1", "missing", "doc-2"], keep_emails=["ta@example.com"])
    assert [r.document_id for r in results] == ["doc-1", "missing", "doc-2"]
    assert results[0].error is None and [d["id"] for d in results[0].downgraded] == ["p-s1"]
    assert results[1].error and "notFound" in results[1].error and results[1].downgraded == []
    assert results[2].error is None


class FakeDocs:
    def __init__(self):
        self.updates: list[tuple[str, list[dict]]] = []

    async def batch_update(self, document_id, requests, required_revision_id=None):
        self.updates.append((document_id, requests))
        return {"replies": [{"replaceAllText": {"occurrencesChanged": 1}} for _ in requests]}


@pytest.mark.asyncio
async def test_create_group_documents_from_google_doc_template_copies_then_replaces_then_shares():
    drive, docs = FakeDrive(), FakeDocs()
    drive.copied = []

    async def copy_file(file_id, name, parent_folder_id=None):
        drive.copied.append((file_id, name, parent_folder_id))
        return {"id": f"copy-{len(drive.copied)}", "name": name, "mimeType": "application/vnd.google-apps.document", "parents": [parent_folder_id]}

    drive.copy_file = copy_file
    results = await usecases.create_group_documents(
        docs, drive, "folder-1", "과제1", "{{activity_name}} - {{team_name}}", None,
        [GroupSpec("A조", ["a1@example.com"])], due="2026-10-10", template_document_id="picked-doc",
    )
    assert drive.copied == [("picked-doc", "과제1 - A조", "folder-1")]  # 원본은 건드리지 않는다
    assert drive.created == []  # Markdown 경로를 타지 않는다
    doc_id, reqs = docs.updates[0]
    assert doc_id == "copy-1"
    assert reqs[0] == {"replaceAllText": {"containsText": {"text": "{{team_name}}", "matchCase": True}, "replaceText": "A조"}}
    assert results[0].replaced == {"team_name": 1, "activity_name": 1, "due": 1}
    assert drive.shared == [("copy-1", "a1@example.com", "writer")]


@pytest.mark.asyncio
async def test_create_group_documents_requires_exactly_one_template():
    with pytest.raises(ValueError):
        await usecases.create_group_documents(None, FakeDrive(), "f", "x", "{{team_name}}", None, [GroupSpec("A조")])
    with pytest.raises(ValueError):
        await usecases.create_group_documents(None, FakeDrive(), "f", "x", "{{team_name}}", "# md", [GroupSpec("A조")], template_document_id="d")
