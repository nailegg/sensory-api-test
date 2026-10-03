"""/google/drive/... 시나리오 엔드포인트. 요청 파싱 → 토큰 → usecases 호출 → 응답. 옮기지 않는다."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.oauth import access_token_dependency
from app.services.google_drive import usecases
from app.services.google_drive.client import DriveApiError, DriveClient

router = APIRouter(prefix="/google/drive", tags=["google_drive"])

google_token = access_token_dependency("google")


def _drive(token: str = Depends(google_token)) -> DriveClient:
    return DriveClient(token)


class CreateFolderRequest(BaseModel):
    name: str
    parent_folder_id: str | None = None


@router.post("/create-folder")
async def create_folder(req: CreateFolderRequest, drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.create_folder(drive, req.name, req.parent_folder_id)
    except DriveApiError as e:
        raise HTTPException(e.status, {"reason": e.reason, "message": e.message, "rate_limit": e.is_rate_limit})


@router.get("/file-meta/{file_id}")
async def file_meta(file_id: str, drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.get_document_meta(drive, file_id)
    except DriveApiError as e:
        raise HTTPException(e.status, {"reason": e.reason, "message": e.message, "rate_limit": e.is_rate_limit})


@router.get("/list-app-files")
async def list_app_files(drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.list_app_files(drive)
    except DriveApiError as e:
        raise HTTPException(e.status, {"reason": e.reason, "message": e.message, "rate_limit": e.is_rate_limit})


@router.post("/move-to-trash/{file_id}")
async def move_to_trash(file_id: str, drive: DriveClient = Depends(_drive)):
    try:
        return await usecases.move_to_trash(drive, file_id)
    except DriveApiError as e:
        raise HTTPException(e.status, {"reason": e.reason, "message": e.message, "rate_limit": e.is_rate_limit})
