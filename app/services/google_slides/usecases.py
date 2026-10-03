"""Slides 시나리오 흐름. 여러 client와 mapper를 엮는다. FastAPI를 import하지 않는다.

유즈케이스(docs/google_slides.md 1절, 2026-10-04 확정: Docs와 같은 4개):
1. 액티비티 폴더 생성 → google_drive.usecases.create_folder
2. 템플릿으로 그룹마다 발표 자료 생성 + 그룹원 편집 권한 → upload_template(액티비티당 1회) + create_group_presentations
3. 마감 시 편집 비활성화 → close_submissions (google_drive.usecases, Docs와 같은 함수)
4. 마감 시 파일로 내보내기 → export_presentation (pptx | pdf | txt | odp)
"""

from app.core.models import Document
from app.services.google_drive.client import MIME_PPTX, MIME_SLIDES, SLIDES_EXPORT_MIME, DriveApiError, DriveClient
from app.services.google_drive.mapper import document_from_drive_file

# 유즈케이스 2 공유 · 3 · 4는 Drive 호출뿐이라 Docs와 같은 함수를 쓴다.
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
from app.services.google_slides.client import SlidesApiError, SlidesClient
from app.services.google_slides.mapper import document_from_slides

# ---------- 읽기·생성 배관 ----------


async def read_presentation(slides: SlidesClient, drive: DriveClient, presentation_id: str) -> Document:
    """모든 슬라이드·표·발표자 노트 평문 + Drive 메타데이터 → Document."""
    presentation = await slides.get(presentation_id)
    drive_file = await drive.get_file(presentation_id)
    return document_from_slides(presentation, drive_file, include_text=True)


async def create_empty_presentation(slides: SlidesClient, drive: DriveClient, title: str, folder_id: str | None = None) -> Document:
    """빈 프레젠테이션 생성 → (선택) 폴더로 이동 → Document. presentations.create는 폴더를 못 정하므로 Drive로 옮긴다."""
    presentation = await slides.create(title)
    presentation_id = presentation["presentationId"]
    drive_file = await drive.move_file(presentation_id, to_folder_id=folder_id) if folder_id else await drive.get_file(presentation_id)
    return document_from_slides(presentation, drive_file)


# ---------- 유즈케이스 2 ----------


async def upload_template(drive: DriveClient, name: str, pptx: bytes, folder_id: str | None = None) -> Document:
    """Synsory가 보관하는 pptx 템플릿을 교수자 Drive에 Slides로 변환 업로드한다(액티비티당 1회).
    앱이 만든 파일이 되므로 drive.file로 files.copy 원본이 될 수 있다. 템플릿 안의 태그는 `{{team_name}}`처럼
    공백 없이 쓰고, 태그 전체를 같은 서식으로 둔다(서식이 갈리면 replaceAllText가 못 찾을 수 있다, 10절 4항)."""
    drive_file = await drive.create_from_content(name, pptx, MIME_PPTX, MIME_SLIDES, folder_id)
    return document_from_drive_file(drive_file)


def replace_tag_requests(variables: dict[str, str]) -> list[dict]:
    """`{{key}}` → 값 치환 요청. 태그 개수와 무관하게 batchUpdate 1회에 담는다(쓰기 쿼터 1).
    matchCase=true로 `{{Team_name}}` 같은 오타에 걸리지 않게 하고, 결과 occurrencesChanged로 템플릿 문제를 찾는다."""
    return [
        {"replaceAllText": {"containsText": {"text": f"{{{{{key}}}}}", "matchCase": True}, "replaceText": value}}
        for key, value in variables.items()
    ]


async def replace_tags(slides: SlidesClient, presentation_id: str, variables: dict[str, str]) -> dict[str, int]:
    """프레젠테이션 전체에서 태그를 치환하고 태그별 치환 횟수를 돌려준다. 0이면 템플릿에 그 태그가 없거나 서식이 갈라진 것."""
    resp = await slides.batch_update(presentation_id, replace_tag_requests(variables))
    replies = resp.get("replies", [])
    return {
        key: (replies[i].get("replaceAllText", {}).get("occurrencesChanged", 0) if i < len(replies) else 0)
        for i, key in enumerate(variables)
    }


# 복사 → 치환 → 공유 흐름은 Sheets(·Docs)와 같아 google_drive.usecases.create_group_files_from_template에 있다. 결과 타입도 공통.
GroupPresentationResult = GroupFileResult


async def create_group_presentations(
    slides: SlidesClient,
    drive: DriveClient,
    folder_id: str,
    activity_name: str,
    title_template: str,
    template_presentation_id: str,
    groups: list[GroupSpec],
    due: str | None = None,
    notify: bool = False,
    share_message: str | None = None,
) -> list[GroupPresentationResult]:
    """그룹마다 템플릿 프레젠테이션을 폴더 안에 복사하고 태그를 치환한 뒤 그룹원에게 편집 권한을 준다.
    그룹당 Drive files.copy 1 + Slides batchUpdate 1 + 그룹원 수만큼 permissions.create.

    template_presentation_id는 ① upload_template 결과(앱이 변환 업로드한 Slides) 또는 ② 교수자가 Picker로 고른 Drive의 기존 Slides.
    둘 다 같은 코드로 동작한다. 원본은 수정하지 않고 복사본만 치환한다. 실패 처리 규칙은 create_group_files_from_template 참고.
    """

    async def _replace(presentation_id: str, variables: dict[str, str]) -> dict[str, int]:
        return await replace_tags(slides, presentation_id, variables)

    return await create_group_files_from_template(
        drive, folder_id, activity_name, title_template, template_presentation_id, groups,
        replace_tags=_replace, replace_errors=(SlidesApiError,), due=due, notify=notify, share_message=share_message,
    )


# ---------- 유즈케이스 3 ----------
# close_submissions · downgrade_editors · restore_editors → google_drive.usecases (위에서 다시 내보냄)


# ---------- 유즈케이스 4 ----------


async def export_presentation(drive: DriveClient, presentation_id: str, fmt: str = "pptx") -> ExportedFile:
    """files.export. pptx | pdf | txt | odp (이미지 형식 없음). 결과는 10MB까지."""
    return await export_file(drive, presentation_id, fmt, SLIDES_EXPORT_MIME)
