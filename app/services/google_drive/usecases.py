"""Drive 흐름. FastAPI를 import하지 않는다.

- Drive 단독 흐름: 폴더 생성, 메타데이터, 목록, 휴지통.
- Docs·Sheets·Slides·Forms 공통 흐름: 템플릿 제목 치환, 그룹원 공유, 마감 시 권한 낮추기·되돌리기, 내보내기.
  이 부분은 Drive 호출뿐이라 서비스마다 다시 만들지 않고 각 서비스의 usecases가 여기서 가져다 쓴다
  (Docs 유즈케이스 3·4를 Slides가 그대로 재사용하면서 2026-10-04 이곳으로 옮김).
"""

import re
from dataclasses import dataclass, field

from app.core.models import Document
from app.services.google_drive.client import DriveApiError, DriveClient
from app.services.google_drive.mapper import document_from_drive_file


async def get_document_meta(drive: DriveClient, file_id: str) -> Document:
    """파일 하나의 메타데이터를 Document로. 인증 3단계에서 첫 실제 호출 검증용으로도 쓴다."""
    return document_from_drive_file(await drive.get_file(file_id))


async def list_app_files(drive: DriveClient, page_size: int = 20) -> list[Document]:
    """drive.file scope로 앱이 접근 가능한 파일 목록."""
    data = await drive.list_files(q="trashed = false", page_size=page_size)
    return [document_from_drive_file(f) for f in data.get("files", [])]


async def create_folder(drive: DriveClient, name: str, parent_folder_id: str | None = None) -> Document:
    """앱 소유 폴더 생성. 이후 Docs 등이 문서를 넣을 수 있는 유일한 폴더가 된다 (drive.file 제약)."""
    return document_from_drive_file(await drive.create_folder(name, parent_folder_id))


async def move_to_trash(drive: DriveClient, file_id: str) -> dict:
    """휴지통으로 이동. 되돌릴 수 있다. 영구 삭제(files.delete)는 별도 시나리오로 다룬다."""
    return await drive.trash_file(file_id)


# ---------- 공통: 템플릿 ----------

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_template(template: str, variables: dict[str, str]) -> str:
    """`{{team_name}}` 형태의 플레이스홀더를 치환한다. 없는 변수는 그대로 둔다 (Markdown의 다른 중괄호와 충돌 방지)."""

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        return str(variables[key]) if key in variables else m.group(0)

    return _PLACEHOLDER.sub(_sub, template)


def group_variables(team_name: str, activity_name: str, due: str | None) -> dict[str, str]:
    """그룹 문서 템플릿에 쓰는 변수. Docs·Slides가 같은 이름을 쓴다."""
    return {"team_name": team_name, "activity_name": activity_name, "due": due or ""}


@dataclass
class GroupSpec:
    team_name: str
    member_emails: list[str] = field(default_factory=list)


# ---------- 공통: 공유 (유즈케이스 2의 뒷부분) ----------


@dataclass
class ShareResult:
    email: str
    ok: bool
    permission_id: str | None = None
    error: str | None = None


async def share_file(
    drive: DriveClient, file_id: str, emails: list[str], role: str = "writer", notify: bool = False, message: str | None = None
) -> list[ShareResult]:
    """그룹원마다 permissions.create. 한 명이 실패해도 나머지는 계속한다."""
    results: list[ShareResult] = []
    for email in emails:
        try:
            perm = await drive.share_with_user(file_id, email, role=role, notify=notify, message=message)
            results.append(ShareResult(email=email, ok=True, permission_id=perm.get("id")))
        except DriveApiError as e:
            results.append(ShareResult(email=email, ok=False, error=f"{e.status} {e.reason}: {e.message}"))
    return results


# ---------- 공통: 마감 (유즈케이스 3) ----------


async def downgrade_editors(
    drive: DriveClient, document_id: str, to_role: str = "commenter", keep_emails: list[str] | None = None
) -> list[dict]:
    """파일 하나의 writer 권한을 to_role로 낮춘다. 소유자(owner)는 조건에 안 걸려 그대로 남는다.
    조교·공동 교수자처럼 writer를 유지해야 하는 사람은 keep_emails로 제외한다. 그룹원 수만큼 호출."""
    keep = {e.lower() for e in keep_emails or []}
    changed: list[dict] = []
    for perm in await drive.list_permissions(document_id):
        if perm.get("role") != "writer" or perm.get("type") not in {"user", "group"}:
            continue
        if (perm.get("emailAddress") or "").lower() in keep:
            continue
        changed.append(await drive.update_permission_role(document_id, perm["id"], to_role))
    return changed


@dataclass
class CloseResult:
    document_id: str
    downgraded: list[dict] = field(default_factory=list)
    error: str | None = None


async def close_submissions(
    drive: DriveClient, document_ids: list[str], to_role: str = "commenter", keep_emails: list[str] | None = None
) -> list[CloseResult]:
    """마감 처리. Synsory 스케줄러가 due 시각에 부른다. 파일마다 downgrade_editors를 실행하고,
    한 파일이 실패해도 나머지를 계속한다. 재실행해도 안전하다(이미 낮춰진 권한은 건너뜀).
    이 다음에 export_file을 호출해 제출본을 확보한다. Docs·Slides 등 파일 종류와 무관하다."""
    results: list[CloseResult] = []
    for document_id in document_ids:
        try:
            changed = await downgrade_editors(drive, document_id, to_role, keep_emails)
            results.append(CloseResult(document_id=document_id, downgraded=changed))
        except DriveApiError as e:
            results.append(CloseResult(document_id=document_id, error=f"{e.status} {e.reason}: {e.message}"))
    return results


async def restore_editors(drive: DriveClient, document_id: str, emails: list[str]) -> list[dict]:
    """되돌리기(마감 연장): 지정한 이메일의 권한을 다시 writer로."""
    wanted = {e.lower() for e in emails}
    changed: list[dict] = []
    for perm in await drive.list_permissions(document_id):
        if (perm.get("emailAddress") or "").lower() in wanted and perm.get("role") != "writer":
            changed.append(await drive.update_permission_role(document_id, perm["id"], "writer"))
    return changed


# ---------- 공통: 내보내기 (유즈케이스 4) ----------


@dataclass
class ExportedFile:
    document_id: str
    filename: str
    mime_type: str
    content: bytes


async def export_file(drive: DriveClient, file_id: str, fmt: str, formats: dict[str, str]) -> ExportedFile:
    """files.export. formats는 서비스별 {확장자: MIME} (client.EXPORT_MIME, SLIDES_EXPORT_MIME).
    Turnitin 등으로의 전송은 호출자(서비스 레포) 책임. 결과는 10MB까지."""
    if fmt not in formats:
        raise ValueError(f"지원하지 않는 형식: {fmt}. 가능: {sorted(formats)}")
    meta = await drive.get_file(file_id, fields="id,name")
    content = await drive.export_file(file_id, formats[fmt])
    return ExportedFile(document_id=file_id, filename=f"{meta['name']}.{fmt}", mime_type=formats[fmt], content=content)
