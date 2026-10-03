"""Slides 응답 dict (+ Drive 메타데이터) → core/models 순수 변환."""

from app.core.models import Document, DocumentKind
from app.services.google_drive.mapper import document_from_drive_file


def _text_content(text: dict | None) -> str:
    """TextContent(textElements[]) → 평문. textRun과 autoText(슬라이드 번호 등)를 이어 붙인다."""
    parts: list[str] = []
    for te in (text or {}).get("textElements", []):
        if "textRun" in te:
            parts.append(te["textRun"].get("content", ""))
        elif "autoText" in te:
            parts.append(te["autoText"].get("content", ""))
    return "".join(parts)


def _text_from_elements(elements: list[dict] | None) -> str:
    """pageElements[] → 평문. 도형 텍스트, 표 셀, 그룹 안 요소까지. 화면 배치 순서가 아니라 요소 배열 순서다."""
    parts: list[str] = []
    for el in elements or []:
        if "shape" in el:
            parts.append(_text_content(el["shape"].get("text")))
        elif "table" in el:
            for row in el["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    parts.append(_text_content(cell.get("text")))
        elif "elementGroup" in el:
            parts.append(_text_from_elements(el["elementGroup"].get("children")))
    return "".join(parts)


def speaker_notes(slide: dict) -> str:
    """슬라이드의 발표자 노트 평문. 노트 페이지에서 speakerNotesObjectId 도형만 본다(슬라이드 썸네일 등은 제외)."""
    notes_page = slide.get("slideProperties", {}).get("notesPage") or {}
    notes_id = notes_page.get("notesProperties", {}).get("speakerNotesObjectId")
    for el in notes_page.get("pageElements", []):
        if el.get("objectId") == notes_id:
            return _text_content(el.get("shape", {}).get("text"))
    return ""


def plain_text(presentation: dict) -> str:
    """presentations.get 응답에서 평문. 슬라이드 순서대로, 슬라이드 본문 뒤에 발표자 노트를 붙이고 슬라이드끼리는 빈 줄로 나눈다.
    마스터·레이아웃의 플레이스홀더 문구("제목을 입력하세요")는 넣지 않는다."""
    chunks: list[str] = []
    for slide in presentation.get("slides", []):
        body = _text_from_elements(slide.get("pageElements"))
        notes = speaker_notes(slide)
        chunks.append(body + (f"[노트] {notes}" if notes.strip() else ""))
    return "\n".join(chunks)


def document_from_slides(presentation: dict, drive_file: dict | None = None, include_text: bool = False) -> Document:
    """Slides `presentations.get`/`create` 응답 + Drive `files.get` 응답 → Document.

    owner·created_at·modified_at·url은 Drive에서만 온다. drive_file이 없으면 그 필드는 비어 있다.
    """
    text = plain_text(presentation) if include_text else None
    if drive_file:
        document = document_from_drive_file(drive_file, text=text)
        return document.model_copy(update={"title": presentation.get("title") or document.title, "kind": DocumentKind.SLIDES})
    return Document(id=presentation["presentationId"], kind=DocumentKind.SLIDES, title=presentation.get("title", ""), text=text)
