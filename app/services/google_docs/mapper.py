"""Docs 응답 dict (+ Drive 메타데이터) → core/models 순수 변환."""

from app.core.models import Document, DocumentKind
from app.services.google_drive.mapper import document_from_drive_file


def _text_from_structural_elements(elements: list[dict]) -> str:
    """body.content / tabs[].documentTab.body.content 에서 평문만 뽑는다. 표·목차 안 문단도 포함."""
    parts: list[str] = []
    for el in elements or []:
        if "paragraph" in el:
            for pe in el["paragraph"].get("elements", []):
                run = pe.get("textRun")
                if run:
                    parts.append(run.get("content", ""))
        elif "table" in el:
            for row in el["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    parts.append(_text_from_structural_elements(cell.get("content", [])))
        elif "tableOfContents" in el:
            parts.append(_text_from_structural_elements(el["tableOfContents"].get("content", [])))
    return "".join(parts)


def plain_text(doc: dict) -> str:
    """documents.get 응답에서 평문. `includeTabsContent=true`면 모든 탭을 순서대로 이어 붙인다."""
    tabs = doc.get("tabs")
    if tabs:
        chunks = []
        for tab in tabs:
            chunks.append(_text_from_structural_elements(tab.get("documentTab", {}).get("body", {}).get("content", [])))
            for child in tab.get("childTabs", []):
                chunks.append(_text_from_structural_elements(child.get("documentTab", {}).get("body", {}).get("content", [])))
        return "".join(chunks)
    return _text_from_structural_elements(doc.get("body", {}).get("content", []))


def document_from_docs(doc: dict, drive_file: dict | None = None, include_text: bool = False) -> Document:
    """Docs `documents.get`/`create` 응답 + Drive `files.get` 응답 → Document.

    owner·created_at·modified_at·url은 Drive에서만 온다. drive_file이 없으면 그 필드는 비어 있다.
    """
    text = plain_text(doc) if include_text else None
    if drive_file:
        document = document_from_drive_file(drive_file, text=text)
        return document.model_copy(update={"title": doc.get("title") or document.title, "kind": DocumentKind.DOC})
    return Document(id=doc["documentId"], kind=DocumentKind.DOC, title=doc.get("title", ""), text=text)
