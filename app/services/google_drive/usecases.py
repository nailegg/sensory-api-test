"""Drive 단독 흐름. Drive는 단독 유즈케이스가 거의 없어 대부분은 Docs 등 다른 서비스의 usecases가 DriveClient를 직접 쓴다.

FastAPI를 import하지 않는다.
"""

from app.core.models import Document
from app.services.google_drive.client import DriveClient
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
