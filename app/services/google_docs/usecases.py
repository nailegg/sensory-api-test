"""Docs 시나리오 흐름. 여러 client와 mapper를 엮는다. FastAPI를 import하지 않는다.

유즈케이스(docs/google_docs.md 1절, 2026-10-03 확정):
1. 액티비티 폴더 생성 → google_drive.usecases.create_folder
2. 템플릿으로 그룹마다 문서 생성 + 그룹원 편집 권한 → create_group_documents
   템플릿 두 방식: ① Synsory가 보관하는 Markdown(그룹마다 변환 업로드) ② 교수자가 Picker로 고른 Google Doc(files.copy → replaceAllText).
   ②는 Slides·Sheets와 같은 공통 함수(google_drive.usecases.create_group_files_from_template). 2026-10-04 상현 승인
3. 마감 시 편집 비활성화 → close_submissions (문서마다 downgrade_editors, 둘 다 google_drive.usecases). 문서 잠금(contentRestrictions) 방식은 교수자도 API 편집이 막혀 쓰지 않기로 함(2026-10-03)
4. 마감 시 파일로 내보내기 → export_document
"""

from app.core.models import Document
from app.services.google_docs.client import DocsApiError, DocsClient
from app.services.google_docs.mapper import document_from_docs
from app.services.google_drive.client import EXPORT_MIME, MIME_DOC, DriveApiError, DriveClient
from app.services.google_drive.mapper import document_from_drive_file

# 유즈케이스 2 공유 · 3 · 4는 Drive 호출뿐이라 Slides와 함께 google_drive.usecases에 둔다.
# 기존 호출부(docs_uc.close_submissions 등)가 그대로 동작하도록 여기서 다시 내보낸다.
from app.services.google_drive.usecases import (  # noqa: F401
    CloseResult,
    ExportedFile,
    GroupFileResult,
    GroupSpec,
    ShareResult,
    close_submissions,
    create_group_files_from_template,
    downgrade_editors,
    export_file,
    group_variables,
    render_template,
    restore_editors,
    share_file,
)


# Markdown 경로(replaced 없음)와 Google Doc 템플릿 경로(replaced 있음) 모두 이 공통 결과 타입을 쓴다.
GroupDocumentResult = GroupFileResult


# ---------- 읽기·생성 배관 ----------


async def read_document(docs: DocsClient, drive: DriveClient, document_id: str) -> Document:
    """문서 본문(평문) + Drive 메타데이터 → Document."""
    doc = await docs.get(document_id, include_tabs_content=True)
    drive_file = await drive.get_file(document_id)
    return document_from_docs(doc, drive_file, include_text=True)


async def create_empty_document(docs: DocsClient, drive: DriveClient, title: str, folder_id: str | None = None) -> Document:
    """빈 문서 생성 → (선택) 폴더로 이동 → Drive 메타데이터 → Document.

    documents.create는 폴더를 못 정하므로 Drive files.update(addParents)로 옮긴다.
    """
    doc = await docs.create(title)
    document_id = doc["documentId"]
    if folder_id:
        drive_file = await drive.move_file(document_id, to_folder_id=folder_id)
    else:
        drive_file = await drive.get_file(document_id)
    return document_from_docs(doc, drive_file)


async def create_document_from_markdown(drive: DriveClient, title: str, markdown: str, folder_id: str | None) -> Document:
    """방식 A: Markdown을 Drive에 올리며 Docs로 변환. 호출 1회, 서식(제목·굵게·목록) 유지."""
    drive_file = await drive.create_from_content(title, markdown, "text/markdown", MIME_DOC, folder_id)
    return document_from_drive_file(drive_file)


async def create_document_with_docs_api(
    docs: DocsClient, drive: DriveClient, title: str, plain_text: str, folder_id: str | None
) -> Document:
    """방식 B: documents.create → batchUpdate insertText(index 1) → 폴더 이동. 호출 3회, 서식 없음(평문).
    서식을 넣으려면 updateParagraphStyle 등을 인덱스 계산과 함께 추가해야 한다. 비교용."""
    doc = await docs.create(title)
    document_id = doc["documentId"]
    if plain_text:
        await docs.batch_update(document_id, [{"insertText": {"location": {"index": 1}, "text": plain_text}}])
    drive_file = await drive.move_file(document_id, to_folder_id=folder_id) if folder_id else await drive.get_file(document_id)
    return document_from_docs(doc, drive_file)


# ---------- 유즈케이스 2 ----------


def replace_tag_requests(variables: dict[str, str]) -> list[dict]:
    """Docs `replaceAllText` 요청(Slides와 같은 모양). `{{key}}` → 값, matchCase=true. tabId를 주지 않으면 모든 탭에 적용된다(10절)."""
    return [
        {"replaceAllText": {"containsText": {"text": f"{{{{{key}}}}}", "matchCase": True}, "replaceText": value}}
        for key, value in variables.items()
    ]


async def replace_tags(docs: DocsClient, document_id: str, variables: dict[str, str]) -> dict[str, int]:
    """문서 전체에서 태그를 치환하고 태그별 치환 횟수(occurrencesChanged)를 돌려준다. 0이면 템플릿에 그 태그가 없는 것."""
    resp = await docs.batch_update(document_id, replace_tag_requests(variables))
    replies = resp.get("replies", [])
    return {
        key: (replies[i].get("replaceAllText", {}).get("occurrencesChanged", 0) if i < len(replies) else 0)
        for i, key in enumerate(variables)
    }


async def create_group_documents(
    docs: DocsClient,
    drive: DriveClient,
    folder_id: str,
    activity_name: str,
    title_template: str,
    body_template: str | None,
    groups: list[GroupSpec],
    due: str | None = None,
    method: str = "markdown",
    notify: bool = False,
    share_message: str | None = None,
    template_document_id: str | None = None,
) -> list[GroupDocumentResult]:
    """그룹마다 템플릿을 채워 폴더 안에 문서를 만들고 그룹원에게 편집 권한을 준다. 템플릿은 둘 중 하나:

    - body_template(Markdown 텍스트): 그룹마다 태그를 텍스트 치환해 Drive 변환 업로드(method=markdown) 또는 Docs API(method=docs_api).
    - template_document_id(Google Doc ID): 교수자가 **Picker로 고른** 기존 문서(또는 앱이 만든 문서)를 그룹마다 Drive files.copy →
      Docs batchUpdate replaceAllText → 공유. Slides·Sheets와 같은 공통 함수. 원본은 수정하지 않고 복사본만 치환한다.
      Picker로 고르지 않은 문서면 그룹마다 files.copy 404 notFound가 error에 담긴다.

    한 그룹이 실패해도 다음 그룹을 계속 만들고, 결과에 error를 담아 돌려준다.
    """
    if (template_document_id is None) == (body_template is None):
        raise ValueError("body_template(Markdown)과 template_document_id(Google Doc 템플릿) 중 하나만 지정한다")
    if template_document_id is not None:

        async def _replace(document_id: str, variables: dict[str, str]) -> dict[str, int]:
            return await replace_tags(docs, document_id, variables)

        return await create_group_files_from_template(
            drive, folder_id, activity_name, title_template, template_document_id, groups,
            replace_tags=_replace, replace_errors=(DocsApiError,), due=due, notify=notify, share_message=share_message,
        )
    results: list[GroupDocumentResult] = []
    for group in groups:
        variables = group_variables(group.team_name, activity_name, due)
        title = render_template(title_template, variables)
        body = render_template(body_template, variables)
        try:
            if method == "docs_api":
                document = await create_document_with_docs_api(docs, drive, title, body, folder_id)
            else:
                document = await create_document_from_markdown(drive, title, body, folder_id)
        except (DriveApiError, DocsApiError) as e:
            results.append(GroupDocumentResult(team_name=group.team_name, document=None, error=str(e)))
            continue
        shares = await share_file(drive, document.id, group.member_emails, notify=notify, message=share_message)
        results.append(GroupDocumentResult(team_name=group.team_name, document=document, shares=shares))
    return results


# ---------- 유즈케이스 3 ----------
# close_submissions · downgrade_editors · restore_editors → google_drive.usecases (위에서 다시 내보냄)


# ---------- 유즈케이스 4 ----------


async def export_document(drive: DriveClient, document_id: str, fmt: str = "docx") -> ExportedFile:
    """files.export. docx | pdf | txt | md | html. Turnitin 등으로의 전송은 호출자(서비스 레포) 책임. 결과는 10MB까지."""
    return await export_file(drive, document_id, fmt, EXPORT_MIME)
