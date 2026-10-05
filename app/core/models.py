"""Synsory 공통 모델. 서비스별 응답은 각 서비스의 mapper.py가 이 모델로 바꾼다.

초안(2026-10-02). 필드는 2단계 유즈케이스가 확정되면서 늘거나 줄 수 있다.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Provider(StrEnum):
    GOOGLE = "google"
    ZOOM = "zoom"


class DocumentKind(StrEnum):
    DOC = "doc"
    SHEET = "sheet"
    SLIDES = "slides"
    FORM = "form"
    FOLDER = "folder"
    FILE = "file"  # 위에 해당하지 않는 Drive 파일


class Document(BaseModel):
    """Google Docs·Sheets·Slides·Forms 공통 표현.

    `owner` · `created_at` · `modified_at` · `url` 은 Drive `files.get`에서 온다.
    각 서비스의 usecases가 자기 API 응답과 Drive 메타데이터를 함께 mapper에 넘긴다.
    """

    id: str
    provider: Provider = Provider.GOOGLE
    kind: DocumentKind
    title: str
    url: str | None = None
    mime_type: str | None = None
    owner: str | None = Field(default=None, description="소유자 표시 이름. 이메일은 샘플 저장 시 마스킹 대상이라 넣지 않는다")
    created_at: datetime | None = None
    modified_at: datetime | None = None
    parent_folder_id: str | None = None
    trashed: bool = Field(default=False, description="Drive 휴지통 여부. 휴지통 문서도 Docs/Drive API는 200을 돌려주므로 호출자가 이 값을 봐야 한다")
    locked: bool = Field(default=False, description="Drive contentRestrictions.readOnly. 마감 잠금 상태")
    text: str | None = Field(default=None, description="본문 평문. 읽기 시나리오에서만 채운다")


class MeetingStatus(StrEnum):
    SCHEDULED = "scheduled"
    STARTED = "started"
    ENDED = "ended"
    UNKNOWN = "unknown"


class MeetingOccurrence(BaseModel):
    """반복 미팅의 한 회차. 회차만 바꾸거나 취소할 때 `id`(Zoom occurrence_id)를 쓴다."""

    id: str
    start_time: datetime | None = None
    duration_minutes: int | None = None
    deleted: bool = False


class Meeting(BaseModel):
    """Zoom 미팅 공통 표현. 필드는 docs/zoom.md 6절. `start_url`은 2시간 만료 + 호스트 권한이라 넣지 않는다."""

    id: str = Field(description="미팅 번호. 10자리를 넘을 수 있어 문자열로 둔다")
    provider: Provider = Provider.ZOOM
    topic: str
    status: MeetingStatus = MeetingStatus.UNKNOWN
    start_time: datetime | None = None
    duration_minutes: int | None = Field(default=None, description="예정 길이. 실제 길이가 아니다")
    timezone: str | None = None
    join_url: str | None = None
    host_id: str | None = None
    uuid: str | None = Field(default=None, description="미팅 인스턴스 식별자. 반복 미팅은 회차마다 새로 생긴다")
    occurrences: list[MeetingOccurrence] = Field(default_factory=list, description="반복 미팅(type 8)의 회차. 최대 50개")
    has_recording: bool = False
    has_transcript: bool = False
