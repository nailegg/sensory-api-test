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


class AnswerGrade(BaseModel):
    """퀴즈 문항 하나의 자동 채점 결과. 채점 대상이 아닌 문항에는 만들지 않는다."""

    score: float = 0
    correct: bool = False
    max_score: float | None = Field(default=None, description="문항 배점(pointValue). 폼 구조를 함께 넘겼을 때만 채운다")


class FormSubmission(BaseModel):
    """설문·퀴즈 응답 한 건. Google Forms `FormResponse`에서 온다(mapper.submission_from_response).

    `answers`의 키는 질문 ID다. 질문 제목은 폼을 만들 때 저장한 매핑(FormInfo.question_ids)으로 찾는다.
    객관식 답은 선택지 문구 그대로라, 생성 후 문구를 바꾸면 예전 응답과 어긋난다.
    """

    id: str
    form_id: str
    provider: Provider = Provider.GOOGLE
    respondent_email: str | None = Field(default=None, description="이메일 수집(VERIFIED·RESPONDER_INPUT)을 켠 폼에서만 온다")
    created_at: datetime | None = None
    submitted_at: datetime | None = Field(default=None, description="마지막 제출 시각(lastSubmittedTime). 채점 변경은 반영되지 않는다")
    answers: dict[str, list[str]] = Field(default_factory=dict, description="질문 ID → 답 문자열 목록(체크박스는 여러 개)")
    file_ids: dict[str, list[str]] = Field(default_factory=dict, description="파일 업로드 질문 ID → Drive 파일 ID 목록")
    total_score: float | None = Field(default=None, description="퀴즈이고 채점된 경우만")
    grades: dict[str, AnswerGrade] = Field(default_factory=dict, description="채점 대상 질문 ID → 채점 결과")
