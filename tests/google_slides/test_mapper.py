from app.core.models import DocumentKind
from app.services.google_slides.mapper import document_from_slides, plain_text, speaker_notes


def _shape(object_id: str, *runs: str) -> dict:
    return {"objectId": object_id, "shape": {"text": {"textElements": [{"paragraphMarker": {}}] + [{"textRun": {"content": r}} for r in runs]}}}


def _slide(object_id: str, elements: list[dict], notes: str | None = None) -> dict:
    notes_page = {
        "notesProperties": {"speakerNotesObjectId": f"{object_id}-notes"},
        "pageElements": [
            {"objectId": f"{object_id}-thumb", "image": {}},  # 노트 페이지의 슬라이드 미리보기
            _shape(f"{object_id}-notes", *([notes] if notes else [])),
        ],
    }
    return {"objectId": object_id, "pageElements": elements, "slideProperties": {"notesPage": notes_page}}


PRESENTATION = {
    "presentationId": "p-1",
    "title": "팀 발표",
    "layouts": [{"pageElements": [_shape("layout-title", "제목을 입력하세요\n")]}],
    "slides": [
        _slide("s1", [_shape("t1", "팀 프로젝트 ", "A조\n"), _shape("st1", "마감 10/10\n")], notes="인사하고 시작\n"),
        _slide(
            "s2",
            [
                {"objectId": "tbl", "table": {"tableRows": [{"tableCells": [{"text": {"textElements": [{"textRun": {"content": "이름\n"}}]}}, {}]}]}},
                {"objectId": "grp", "elementGroup": {"children": [_shape("g1", "그룹 안 😀\n")]}},
                {"objectId": "img", "image": {}},
            ],
        ),
    ],
}


def test_plain_text_orders_slides_and_appends_notes_without_layouts():
    assert plain_text(PRESENTATION) == "팀 프로젝트 A조\n마감 10/10\n[노트] 인사하고 시작\n\n이름\n그룹 안 😀\n"


def test_speaker_notes_ignores_other_notes_page_elements():
    assert speaker_notes(PRESENTATION["slides"][0]) == "인사하고 시작\n"
    assert speaker_notes(PRESENTATION["slides"][1]) == ""
    assert speaker_notes({"objectId": "x"}) == ""


def test_document_from_slides_merges_drive_meta():
    drive_file = {
        "id": "p-1",
        "name": "drive 이름",
        "mimeType": "application/vnd.google-apps.presentation",
        "webViewLink": "https://docs.google.com/presentation/d/p-1/edit",
        "owners": [{"displayName": "Tester"}],
        "parents": ["folder-1"],
    }
    d = document_from_slides(PRESENTATION, drive_file, include_text=True)
    assert d.kind == DocumentKind.SLIDES and d.title == "팀 발표" and d.owner == "Tester" and d.parent_folder_id == "folder-1"
    assert d.text and d.text.startswith("팀 프로젝트 A조")


def test_document_from_slides_without_drive():
    d = document_from_slides(PRESENTATION)
    assert d.id == "p-1" and d.kind == DocumentKind.SLIDES and d.url is None and d.text is None
