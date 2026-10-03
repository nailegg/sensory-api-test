from datetime import UTC, datetime

from app.core.models import DocumentKind
from app.services.google_drive.mapper import document_from_drive_file, kind_from_mime

DRIVE_FILE = {
    "id": "file-1",
    "name": "회의록",
    "mimeType": "application/vnd.google-apps.document",
    "webViewLink": "https://docs.google.com/document/d/file-1/edit",
    "createdTime": "2026-09-30T12:00:00.000Z",
    "modifiedTime": "2026-10-01T01:02:03.000Z",
    "owners": [{"displayName": "Tester"}],
    "parents": ["folder-1"],
    "trashed": False,
}


def test_document_from_drive_file():
    d = document_from_drive_file(DRIVE_FILE)
    assert d.id == "file-1"
    assert d.kind == DocumentKind.DOC
    assert d.title == "회의록"
    assert d.owner == "Tester"
    assert d.parent_folder_id == "folder-1"
    assert d.created_at == datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    assert d.modified_at == datetime(2026, 10, 1, 1, 2, 3, tzinfo=UTC)
    assert d.text is None
    assert d.trashed is False


def test_missing_optional_fields():
    d = document_from_drive_file({"id": "x", "name": "n"})
    assert d.kind == DocumentKind.FILE
    assert d.owner is None and d.parent_folder_id is None and d.url is None


def test_kind_from_mime():
    assert kind_from_mime("application/vnd.google-apps.spreadsheet") == DocumentKind.SHEET
    assert kind_from_mime("application/vnd.google-apps.presentation") == DocumentKind.SLIDES
    assert kind_from_mime("application/vnd.google-apps.form") == DocumentKind.FORM
    assert kind_from_mime("application/pdf") == DocumentKind.FILE
    assert kind_from_mime(None) == DocumentKind.FILE


def test_trashed_flag():
    assert document_from_drive_file({**DRIVE_FILE, "trashed": True}).trashed is True


def test_locked_flag_from_content_restrictions():
    assert document_from_drive_file({**DRIVE_FILE, "contentRestrictions": [{"readOnly": True, "reason": "마감"}]}).locked is True
    assert document_from_drive_file({**DRIVE_FILE, "contentRestrictions": [{"readOnly": False}]}).locked is False
    assert document_from_drive_file(DRIVE_FILE).locked is False
