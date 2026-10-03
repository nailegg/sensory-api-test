from app.core.models import DocumentKind
from app.services.google_docs.mapper import document_from_docs, plain_text


def _para(text: str) -> dict:
    return {"paragraph": {"elements": [{"textRun": {"content": text}}]}}


SINGLE_TAB_DOC = {
    "documentId": "doc-1",
    "title": "제목",
    "body": {"content": [{"sectionBreak": {}}, _para("첫 줄\n"), _para("둘째 줄 😀\n")]},
}

TABBED_DOC = {
    "documentId": "doc-2",
    "title": "탭 문서",
    "tabs": [
        {
            "documentTab": {"body": {"content": [_para("탭1\n")]}},
            "childTabs": [{"documentTab": {"body": {"content": [_para("자식탭\n")]}}}],
        },
        {"documentTab": {"body": {"content": [_para("탭2\n")]}}},
    ],
}

TABLE_DOC = {
    "documentId": "doc-3",
    "title": "표",
    "body": {
        "content": [
            {
                "table": {
                    "tableRows": [
                        {"tableCells": [{"content": [_para("a")]}, {"content": [_para("b")]}]},
                    ]
                }
            }
        ]
    },
}

DRIVE_FILE = {
    "id": "doc-1",
    "name": "Drive쪽 이름",
    "mimeType": "application/vnd.google-apps.document",
    "webViewLink": "https://docs.google.com/document/d/doc-1/edit",
    "createdTime": "2026-09-30T12:00:00Z",
    "modifiedTime": "2026-09-30T13:00:00Z",
    "owners": [{"displayName": "Tester"}],
}


def test_plain_text_single_tab():
    assert plain_text(SINGLE_TAB_DOC) == "첫 줄\n둘째 줄 😀\n"


def test_plain_text_all_tabs_in_order():
    assert plain_text(TABBED_DOC) == "탭1\n자식탭\n탭2\n"


def test_plain_text_table_cells():
    assert plain_text(TABLE_DOC) == "ab"


def test_document_with_drive_meta():
    d = document_from_docs(SINGLE_TAB_DOC, DRIVE_FILE, include_text=True)
    assert d.kind == DocumentKind.DOC
    assert d.title == "제목"  # Docs 쪽 title 우선
    assert d.owner == "Tester"
    assert d.url and d.url.endswith("/doc-1/edit")
    assert d.text == "첫 줄\n둘째 줄 😀\n"


def test_document_without_drive_meta():
    d = document_from_docs(SINGLE_TAB_DOC)
    assert d.id == "doc-1" and d.owner is None and d.created_at is None and d.text is None
